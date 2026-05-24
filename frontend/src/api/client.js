import axios from 'axios'

// In dev: Vite proxies /api → localhost:8080
// In prod: set VITE_API_BASE_URL=https://your-api.onrender.com in Vercel env vars
const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api',
  timeout: 90000,
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    console.error('[API Error]', {
      url: err.config?.url,
      method: err.config?.method,
      status: err.response?.status,
      responseData: err.response?.data,
      message: err.message,
    })
    const msg =
      err.response?.data?.detail ||
      err.response?.data?.message ||
      err.message ||
      'Unknown error'
    return Promise.reject(new Error(msg))
  }
)

export default client
