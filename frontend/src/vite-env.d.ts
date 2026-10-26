/// <reference types="vite/client" />

declare const posthog: {
  init: (apiKey: string, options?: Record<string, any>) => void
  capture: (event: string, properties?: Record<string, any>) => void
  identify: (id: string, properties?: Record<string, any>) => void
  reset: () => void
}

declare namespace API {
  type AuthProvider = "google" | "phone"

  type User = {
    id: string
    name: string
    avatar?: string
    phone?: string
    credits: number
  }

  type ChatThread = {
    id: string
    title: string
    created_at: string
  }

  type Message = {
    id: string
    type: "ai" | "user" | "factor" | "backtest"
    content: string
    factor: any
  }

  type FactorRecord = {
    id: string
    index: number
    name: string
    expr: string
    created_at: string
    backtest_result: Record<string, number>
  }

  type FactorBacktestResult = {
    id: string
    params: Record<string, number | string>
    results: Record<string, number | string>
    ic_detail: {
      datetime: string
      return: number
      bench: number
    }[]
    report_normal: {
      datetime: string
      return: number
      bench: number
    }[]
    created_at: string
  }
}
