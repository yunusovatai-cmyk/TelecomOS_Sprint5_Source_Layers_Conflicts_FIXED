import axios from "axios";

export const apiBaseUrl = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000/api/v1";

export const api = axios.create({
  baseURL: apiBaseUrl,
});
