// reverse_stress_core.cpp
// -----------------------------------------------------------------------------
// Native (C++) port of the deterministic reverse-stress search core.
//
// This mirrors the pure-math + search loop of
// liquidity_risk_tool/engines/reverse_stress_engine.py exactly:
//
//   * Mahalanobis severity norm   D(s) = sqrt(s^T P s)   (P = precision = Σ⁻¹)
//   * coherence guardrail          max(liquidity sev) ≤ max(market sev) + α
//   * coarse grid seeding + breach-boundary midpoint refinement
//   * radial ray bisection back toward calm
//   * coordinate (axis-by-axis) boundary-walk polish
//
// What stays in Python:
//   * the expensive portfolio repricing (StressEngine._apply_scenario). It is
//     handed in as the `oracle` callback: given a severity vector it returns
//     (liquid_pct_after, can_meet_redemption). This file never reprices.
//   * the precision matrix (built once with numpy.pinv) and the scipy SLSQP
//     multistart refinement, which remain on the Python side; the native core
//     can be seeded with SLSQP winners and will still ray+coordinate polish them.
//
// The result mirrors ReverseStressResult's search-relevant fields; Python wraps
// it back into the full dataclass + StressScenario.
// -----------------------------------------------------------------------------
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>

#include <algorithm>
#include <cmath>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace py = pybind11;

namespace {

// The breach oracle: severity vector -> (liquid_pct_after, can_meet_redemption).
// One call == one portfolio repricing on the Python side.
using Oracle = std::function<std::pair<double, bool>(const std::vector<double>&)>;

inline double clip01(double x) { return x < 0.0 ? 0.0 : (x > 1.0 ? 1.0 : x); }

std::vector<double> clip01v(const std::vector<double>& s) {
    std::vector<double> out(s.size());
    for (size_t i = 0; i < s.size(); ++i) out[i] = clip01(s[i]);
    return out;
}

// Quantise a severity vector to 4 dp so the cache collapses revisited points,
// matching the Python `round(x, 4)` cache key.
std::vector<double> quantise(const std::vector<double>& s) {
    std::vector<double> q(s.size());
    for (size_t i = 0; i < s.size(); ++i) q[i] = std::round(clip01(s[i]) * 1e4) / 1e4;
    return q;
}

// The search core. Holds the precision matrix, coherence axis groupings, the
// evaluation cache + budget, and the oracle. One Engine per solve.
class SearchCore {
public:
    SearchCore(std::vector<std::vector<double>> precision,
               std::vector<int> market_idx,
               std::vector<int> liquidity_idx,
               double coherence_autonomy,
               double target_liquid_pct,
               Oracle oracle,
               int eval_budget)
        : precision_(std::move(precision)),
          market_idx_(std::move(market_idx)),
          liquidity_idx_(std::move(liquidity_idx)),
          coherence_autonomy_(coherence_autonomy),
          target_(target_liquid_pct),
          oracle_(std::move(oracle)),
          eval_budget_(eval_budget),
          dim_(static_cast<int>(precision_.size())) {}

    int n_eval() const { return n_eval_; }

    // --- evaluation (cached, budgeted) ---------------------------------------
    std::pair<double, bool> evaluate(const std::vector<double>& s, bool force) {
        auto key = quantise(s);
        auto it = cache_.find(key);
        if (it != cache_.end()) return it->second;
        if (!force && eval_budget_ >= 0 && n_eval_ >= eval_budget_) {
            // Budget spent: return a non-breaching sentinel so the search settles
            // on the best point already found (matches the Python guard exactly).
            return {1.0, true};
        }
        auto out = oracle_(key);          // the single expensive call
        ++n_eval_;
        cache_.emplace(key, out);
        return out;
    }

    double liquid_after(const std::vector<double>& s) { return evaluate(s, false).first; }
    bool is_breach(const std::vector<double>& s) { return !evaluate(s, false).second; }
    double breach_margin(const std::vector<double>& s) { return target_ - liquid_after(s); }

    // Breach test that bypasses the evaluation-budget guard. Used inside the
    // boundary polish (refine_along_ray / refine_coordinate), where the budget
    // sentinel {1.0, true} (non-breach) would falsely clear a genuine breach and
    // make the bisection keep the over-severe seed instead of the closer point it
    // is probing. The polish visits only a small, bounded number of points, so
    // forcing them is cheap. Mirrors Python's _is_breach_forced exactly.
    bool is_breach_forced(const std::vector<double>& s) { return !evaluate(s, true).second; }

    // --- Mahalanobis severity norm  D(s) = sqrt(s^T P s) ---------------------
    double distance(const std::vector<double>& s_in) const {
        auto s = clip01v(s_in);
        double q = 0.0;
        for (int i = 0; i < dim_; ++i) {
            double row = 0.0;
            for (int j = 0; j < dim_; ++j) row += precision_[i][j] * s[j];
            q += s[i] * row;
        }
        if (q < 0.0) q = 0.0;
        return std::sqrt(q + 1e-12);
    }

    // P·s, used to rank each axis's marginal contribution in the coord walk.
    std::vector<double> precision_times(const std::vector<double>& s) const {
        std::vector<double> out(dim_, 0.0);
        for (int i = 0; i < dim_; ++i)
            for (int j = 0; j < dim_; ++j) out[i] += precision_[i][j] * s[j];
        return out;
    }

    // --- coherence guardrail -------------------------------------------------
    double coherence_margin(const std::vector<double>& s_in) const {
        auto s = clip01v(s_in);
        if (market_idx_.empty() || liquidity_idx_.empty()) return 1.0;  // inactive
        double max_market = 0.0, max_liq = 0.0;
        for (int i : market_idx_) max_market = std::max(max_market, s[i]);
        for (int i : liquidity_idx_) max_liq = std::max(max_liq, s[i]);
        return max_market + coherence_autonomy_ - max_liq;
    }
    bool is_coherent(const std::vector<double>& s) const {
        return coherence_margin(s) >= -1e-9;
    }

    // --- radial ray bisection back toward calm -------------------------------
    // D is a norm, so D(t·s) = t·D(s) is monotone in t; the least-severe point on
    // the calm->breach ray is the smallest t that still breaches coherently.
    std::pair<double, std::vector<double>> refine_along_ray(
        const std::vector<double>& s_breach_in, int n_bisect = 18) {
        auto s_breach = clip01v(s_breach_in);
        if (!is_breach_forced(s_breach)) return {distance(s_breach), s_breach};
        double lo = 0.0, hi = 1.0;  // lo: known non-breach (calm), hi: known breach
        for (int k = 0; k < n_bisect; ++k) {
            double mid = 0.5 * (lo + hi);
            auto s_mid = scaled(s_breach, mid);
            if (is_coherent(s_mid) && is_breach_forced(s_mid)) hi = mid;
            else lo = mid;
        }
        auto s_star = scaled(s_breach, hi);
        return {distance(s_star), s_star};
    }

    // --- coordinate boundary-walk polish -------------------------------------
    // Shrink each axis individually toward calm while the point keeps breaching
    // coherently, relaxing the highest-D-contribution axes first. Captures the
    // sideways gains the radial ray structurally cannot.
    std::pair<double, std::vector<double>> refine_coordinate(
        const std::vector<double>& s_in, int n_passes = 2, int n_bisect = 12) {
        auto s = clip01v(s_in);
        if (!(is_breach_forced(s) && is_coherent(s))) return {distance(s), s};
        for (int pass = 0; pass < n_passes; ++pass) {
            bool improved = false;
            auto ps = precision_times(s);
            std::vector<int> order(dim_);
            for (int i = 0; i < dim_; ++i) order[i] = i;
            std::vector<double> contrib(dim_);
            for (int i = 0; i < dim_; ++i) contrib[i] = ps[i] * s[i];
            std::sort(order.begin(), order.end(),
                      [&](int a, int b) { return contrib[a] > contrib[b]; });
            for (int i : order) {
                if (s[i] <= 1e-6) continue;
                double lo = 0.0, hi = s[i];
                auto trial = s;
                trial[i] = lo;
                if (is_breach_forced(trial) && is_coherent(trial)) {
                    if (std::fabs(s[i]) > 1e-9) improved = true;
                    s[i] = 0.0;
                    continue;
                }
                for (int k = 0; k < n_bisect; ++k) {
                    double mid = 0.5 * (lo + hi);
                    trial[i] = mid;
                    if (is_breach_forced(trial) && is_coherent(trial)) hi = mid;
                    else lo = mid;
                }
                if (hi < s[i] - 1e-6) { s[i] = hi; improved = true; }
            }
            if (!improved) break;
        }
        return {distance(s), s};
    }

    // --- the full deterministic search ---------------------------------------
    // Returns a status string + the winning severity vector + its distance.
    // SLSQP (Python) may pre-seed `extra_seeds`; each is ray+coord polished too.
    py::dict solve(int grid_per_axis,
                   const std::vector<std::vector<double>>& extra_seeds) {
        py::dict out;
        std::vector<double> s_zero(dim_, 0.0);
        auto [liquid_zero, can_meet_zero] = evaluate(s_zero, false);

        // 0. already in breach with no shock?
        if (is_breach(s_zero)) {
            out["status"] = "baseline-breach";
            out["s"] = s_zero;
            out["distance"] = 0.0;
            out["baseline_liquid_pct"] = liquid_zero;
            out["n_eval"] = n_eval_;
            return out;
        }

        // 1. feasibility at the severe corner
        std::vector<double> s_max(dim_, 1.0);
        double corner_distance = distance(s_max);
        if (!is_breach(s_max)) {
            out["status"] = "infeasible";
            out["baseline_liquid_pct"] = liquid_zero;
            out["corner_distance"] = corner_distance;
            out["n_eval"] = n_eval_;
            return out;
        }

        // 2. coarse grid + record breach verdicts for boundary refinement
        std::vector<double> grid_vals(grid_per_axis);
        for (int i = 0; i < grid_per_axis; ++i)
            grid_vals[i] = grid_per_axis == 1 ? 0.0
                                              : double(i) / double(grid_per_axis - 1);
        std::vector<std::pair<double, std::vector<double>>> feasible;  // (dist, s)
        std::vector<std::vector<double>> breachers, non_breachers;

        std::vector<int> digit(dim_, 0);
        bool done = false;
        // budget-cap the grid like Python: stride-decimate if it would overrun.
        long long raw = 1;
        for (int i = 0; i < dim_; ++i) raw *= grid_per_axis;
        long long max_grid_points =
            std::max(static_cast<long long>(32),
                     eval_budget_ < 0 ? raw : static_cast<long long>(eval_budget_) / 2);
        long long stride = raw > max_grid_points ? std::max(1LL, raw / max_grid_points) : 1;
        long long counter = 0;
        while (!done) {
            if (counter % stride == 0) {
                std::vector<double> s(dim_);
                for (int i = 0; i < dim_; ++i) s[i] = grid_vals[digit[i]];
                bool b = is_coherent(s) && is_breach(s);
                if (b) { breachers.push_back(s); feasible.push_back({distance(s), s}); }
                else non_breachers.push_back(s);
            }
            ++counter;
            int pos = dim_ - 1;
            while (pos >= 0) {
                if (++digit[pos] < grid_per_axis) break;
                digit[pos] = 0;
                --pos;
            }
            if (pos < 0) done = true;
        }

        // 2b. breach-boundary midpoint refinement
        int refine_cap = std::max(8, eval_budget_ < 0 ? 64 : eval_budget_ / 6);
        int n_refined = 0;
        for (const auto& sb : breachers) {
            if (n_refined >= refine_cap || non_breachers.empty()) break;
            double best_d = 1e300; const std::vector<double>* sn = nullptr;
            for (const auto& cand : non_breachers) {
                double d = 0.0;
                for (int i = 0; i < dim_; ++i) { double dd = sb[i] - cand[i]; d += dd * dd; }
                if (d < best_d) { best_d = d; sn = &cand; }
            }
            std::vector<double> mid(dim_);
            for (int i = 0; i < dim_; ++i) mid[i] = 0.5 * (sb[i] + (*sn)[i]);
            if (is_coherent(mid) && is_breach(mid)) feasible.push_back({distance(mid), mid});
            ++n_refined;
        }

        // 3. SLSQP-provided seeds (already optimised on the Python side)
        std::string method = "grid";
        for (const auto& seed : extra_seeds) {
            auto s = clip01v(seed);
            if (is_coherent(s) && is_breach(s)) {
                feasible.push_back({distance(s), s});
                method = "SLSQP+multistart";
            }
        }

        std::optional<std::pair<double, std::vector<double>>> best;
        for (const auto& f : feasible)
            if (!best || f.first < best->first) best = f;
        if (!best) { best = {distance(s_max), s_max}; method = "grid"; }

        // 3b. ray-bisection polish
        auto [d_ray, s_ray] = refine_along_ray(best->second);
        if (is_breach_forced(s_ray) && is_coherent(s_ray)) {
            if (d_ray < best->first - 1e-9)
                method = (method == "grid") ? "ray-bisection" : method + "+ray";
            best = {d_ray, s_ray};
        }

        // 3c. coordinate boundary-walk polish
        auto [d_co, s_co] = refine_coordinate(best->second);
        if (is_breach_forced(s_co) && is_coherent(s_co) && d_co < best->first - 1e-9) {
            best = {d_co, s_co};
            bool ends_ray = method.size() >= 3 && method.substr(method.size() - 3) == "ray";
            if (!ends_ray && method.find("coord") == std::string::npos)
                method = (method == "grid") ? "coordinate-walk" : method + "+coord";
            else
                method += "+coord";
        }

        out["status"] = "found";
        out["method"] = method;
        out["s"] = best->second;
        out["distance"] = best->first;
        out["corner_distance"] = corner_distance;
        out["baseline_liquid_pct"] = liquid_zero;
        out["n_eval"] = n_eval_;
        return out;
    }

private:
    static std::vector<double> scaled(const std::vector<double>& s, double t) {
        std::vector<double> out(s.size());
        for (size_t i = 0; i < s.size(); ++i) out[i] = t * s[i];
        return out;
    }

    std::vector<std::vector<double>> precision_;
    std::vector<int> market_idx_, liquidity_idx_;
    double coherence_autonomy_;
    double target_;
    Oracle oracle_;
    int eval_budget_;
    int dim_;
    int n_eval_ = 0;
    std::map<std::vector<double>, std::pair<double, bool>> cache_;
};

}  // namespace

PYBIND11_MODULE(reverse_stress_core, m) {
    m.doc() = "Native reverse-stress search core (Mahalanobis distance, coherence "
              "guardrail, grid+boundary seeding, ray + coordinate polish).";

    py::class_<SearchCore>(m, "SearchCore")
        .def(py::init<std::vector<std::vector<double>>, std::vector<int>,
                      std::vector<int>, double, double, Oracle, int>(),
             py::arg("precision"), py::arg("market_idx"), py::arg("liquidity_idx"),
             py::arg("coherence_autonomy"), py::arg("target_liquid_pct"),
             py::arg("oracle"), py::arg("eval_budget"))
        .def("distance", &SearchCore::distance)
        .def("coherence_margin", &SearchCore::coherence_margin)
        .def("is_coherent", &SearchCore::is_coherent)
        .def("solve", &SearchCore::solve, py::arg("grid_per_axis"),
             py::arg("extra_seeds") = std::vector<std::vector<double>>{})
        .def_property_readonly("n_eval", &SearchCore::n_eval);
}
