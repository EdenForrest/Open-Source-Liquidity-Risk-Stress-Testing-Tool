using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

class StartDevServers
{
    static void Main(string[] args)
    {
        string projectRoot = AppDomain.CurrentDomain.BaseDirectory;
        string frontendPath = Path.Combine(projectRoot, "frontend");

        Console.ForegroundColor = ConsoleColor.Cyan;
        Console.WriteLine("🚀 Liquidity Risk Tool — Starting backend and frontend...");
        Console.ResetColor();
        Console.WriteLine($"Project root: {projectRoot}\n");

        // Verify Python is available
        if (!CommandExists("python"))
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("❌ Error: Python not found. Ensure Python is in PATH.");
            Console.ResetColor();
            Console.WriteLine("Press any key to exit...");
            Console.ReadKey();
            return;
        }

        // Verify npm is available
        if (!CommandExists("npm"))
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("❌ Error: npm not found. Ensure Node.js is in PATH.");
            Console.ResetColor();
            Console.WriteLine("Press any key to exit...");
            Console.ReadKey();
            return;
        }

        // Start backend
        Console.ForegroundColor = ConsoleColor.Green;
        Console.WriteLine("▶️  Backend (FastAPI on port 8080)...");
        Console.ResetColor();

        var backendProcess = new ProcessStartInfo
        {
            FileName = "cmd.exe",
            Arguments = "/k python -m uvicorn backend.main:app --reload --port 8080",
            WorkingDirectory = projectRoot,
            UseShellExecute = true,
            CreateNoWindow = false
        };

        var backend = Process.Start(backendProcess);

        // Wait briefly for backend to start
        Thread.Sleep(3000);

        // Start frontend
        Console.ForegroundColor = ConsoleColor.Green;
        Console.WriteLine("▶️  Frontend (Vite dev server on port 5173)...");
        Console.ResetColor();

        var frontendProcess = new ProcessStartInfo
        {
            FileName = "cmd.exe",
            Arguments = "/k npm run dev",
            WorkingDirectory = frontendPath,
            UseShellExecute = true,
            CreateNoWindow = false
        };

        var frontend = Process.Start(frontendProcess);

        Console.WriteLine();
        Console.ForegroundColor = ConsoleColor.Green;
        Console.WriteLine("✅ Both services started!");
        Console.ResetColor();
        Console.WriteLine();
        Console.ForegroundColor = ConsoleColor.Cyan;
        Console.WriteLine("Backend:  http://localhost:8080/docs");
        Console.WriteLine("Frontend: http://localhost:5173");
        Console.ResetColor();
        Console.WriteLine();
        Console.ForegroundColor = ConsoleColor.Gray;
        Console.WriteLine("The command windows will stay open. Close them to stop the services.");
        Console.ResetColor();

        // Wait for both processes to exit
        Task.WaitAll(
            Task.Run(() => backend?.WaitForExit()),
            Task.Run(() => frontend?.WaitForExit())
        );

        Console.WriteLine("\n✋ Services stopped.");
    }

    static bool CommandExists(string command)
    {
        var processInfo = new ProcessStartInfo
        {
            FileName = "where",
            Arguments = command,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };

        try
        {
            using (var process = Process.Start(processInfo))
            {
                process.WaitForExit();
                return process.ExitCode == 0;
            }
        }
        catch
        {
            return false;
        }
    }
}
