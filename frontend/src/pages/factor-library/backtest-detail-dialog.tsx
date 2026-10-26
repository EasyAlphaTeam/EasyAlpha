import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { useRequest } from "ahooks"
import { getFactorBacktestDetail } from "@/lib/service.ts"
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts"
import { cn } from "@/lib/utils"

type BacktestDetailDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  factorId?: string
}

const metricLabels: Record<string, string> = {
  ICIR: "ICIR",
  "IC Mean": "IC Mean",
  "Rank ICIR": "Rank ICIR",
  "Max Drawdown": "Max Drawdown",
  "Rank IC Mean": "Rank IC Mean",
  "Annual Return": "Annual Return",
  "Information Ratio": "Information Ratio",
}

const paramOrder: string[] = [
  "start_time",
  "end_time",
  "account",
  "topk",
  "benchmark",
  "hold_days",
  "deal_price",
  "open_cost",
  "close_cost",
  "min_cost",
  "limit_threshold",
]

const paramLabels: Record<string, string> = {
  topk: "Top K Stocks",
  account: "Initial Capital (¥)",
  start_time: "Start Time",
  end_time: "End Time",
  min_cost: "Minimum Transaction Fee (¥)",
  benchmark: "Benchmark Index",
  hold_days: "Holding Period (Days)",
  open_cost: "Buy Transaction Fee (%)",
  close_cost: "Sell Transaction Fee (%)",
  deal_price: "Deal Price",
  limit_threshold: "Limit Threshold",
}

const chartConfig = {
  ic: {
    label: "IC",
    color: "var(--chart-1)",
  },
  rank_ic: {
    label: "Rank IC",
    color: "var(--chart-2)",
  },
  return: {
    label: "Strategy Returns",
    color: "var(--chart-1)",
  },
  bench: {
    label: "Benchmark Returns",
    color: "var(--chart-3)",
  },
} satisfies ChartConfig

const percentMetricKeys = new Set(["Annual Return", "Max Drawdown"])

const formatDate = (value?: string) => {
  if (!value) return "--"

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date)
}

const formatMetric = (key: string, value?: number) => {
  if (value == null || Number.isNaN(value)) return "--"
  if (percentMetricKeys.has(key)) return `${(value * 100).toFixed(2)}%`
  return value.toFixed(4)
}

const formatPercentTick = (value: number) => `${(value * 100).toFixed(1)}%`

const formatParamValue = (value: string | number, type: string) => {
  if (typeof value === "number") {
    if (["open_costq", "close_cost", "limit_threshold"].includes(type)) {
      value = value * 100
      return `${value.toFixed(2)}%`
    } else {
      return Number.isInteger(value) ? `${value}` : value.toFixed(4)
    }
  }

  if (type === "deal_price") {
    return value === "open"
      ? "Open Price Buy"
      : value === "close"
        ? "Close Price Buy"
        : ""
  }

  return value
}

function MetricCard({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent?: "positive" | "negative"
}) {
  return (
    <Card className="gap-3 border border-border/60 py-3">
      <CardHeader className="px-3">
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent className="px-3">
        <div
          className={cn(
            "text-xl font-semibold tabular-nums",
            accent === "positive" && "text-red-600",
            accent === "negative" && "text-emerald-600"
          )}
        >
          {value}
        </div>
      </CardContent>
    </Card>
  )
}

function SectionSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-24 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Skeleton className="h-80 rounded-xl" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
      <Skeleton className="h-40 rounded-xl" />
    </div>
  )
}

export function BacktestDetailDialog({
  open,
  onOpenChange,
  factorId,
}: BacktestDetailDialogProps) {
  const { data, loading } = useRequest(
    async () => {
      if (factorId && open) {
        return await getFactorBacktestDetail({ factorId })
      }
    },
    {
      refreshDeps: [factorId, open],
    }
  )
  const results = data?.results ?? {}
  const params = data?.params ?? {}
  const icDetail = data?.ic_detail ?? []
  const reportNormal = data?.report_normal ?? []
  const summaryMetrics = Object.entries(metricLabels)
  const hasCharts = icDetail
    ? icDetail.length > 0 || reportNormal.length > 0
    : false

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] p-0 sm:max-w-5xl">
        <DialogHeader>
          <div className="border-b border-border/60 px-6 pt-6 pb-4">
            <DialogTitle>Backtest Detail</DialogTitle>
          </div>
        </DialogHeader>
        <ScrollArea className="max-h-[calc(90vh-5rem)]">
          <div className="space-y-4 p-6 pt-0" data-factor-id={factorId}>
            {loading ? (
              <SectionSkeleton />
            ) : !data ? (
              <Card className="border border-dashed border-border/60">
                <CardContent className="py-12 text-center text-sm text-muted-foreground">
                  No backtest data available
                </CardContent>
              </Card>
            ) : (
              <>
                <Card className="border border-border/60">
                  <CardHeader>
                    <CardTitle>回测结果</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                      {summaryMetrics.map(([key, label]) => {
                        const _value = results[key]
                        const value =
                          typeof _value === "string"
                            ? parseFloat(_value)
                            : _value
                        const accent =
                          key === "Annual Return"
                            ? value != null && value > 0
                              ? "positive"
                              : undefined
                            : key === "Max Drawdown"
                              ? value != null && value < 0
                                ? "negative"
                                : undefined
                              : undefined

                        return (
                          <MetricCard
                            key={key}
                            label={label}
                            value={formatMetric(key, value)}
                            accent={accent}
                          />
                        )
                      })}
                    </div>
                  </CardContent>
                </Card>

                <Card className="border border-border/60">
                  <CardHeader>
                    <CardTitle>Cumulative Returns</CardTitle>
                    <CardDescription>
                      Strategy returns vs benchmark returns over time
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {reportNormal.length ? (
                      <ChartContainer
                        config={chartConfig}
                        className="h-80 w-full"
                      >
                        <LineChart
                          data={reportNormal}
                          margin={{ left: 8, right: 8, top: 8 }}
                        >
                          <defs>
                            <linearGradient
                              id="benchGradient"
                              x1="0"
                              y1="0"
                              x2="1"
                              y2="0"
                            >
                              <stop offset="0%" stopColor="#06b6d4" />
                              <stop offset="100%" stopColor="#024a70" />
                            </linearGradient>
                          </defs>

                          <CartesianGrid vertical={false} />
                          <XAxis
                            dataKey="datetime"
                            tickLine={false}
                            axisLine={false}
                            minTickGap={32}
                            tickFormatter={formatDate}
                          />
                          <YAxis
                            tickLine={false}
                            axisLine={false}
                            width={64}
                            tickFormatter={formatPercentTick}
                          />
                          <ChartTooltip
                            content={
                              <ChartTooltipContent
                                labelFormatter={(label) =>
                                  formatDate(String(label))
                                }
                                formatter={(value, name) => (
                                  <>
                                    <span className="text-muted-foreground">
                                      {chartConfig[String(name)]?.label ??
                                        String(name)}
                                    </span>
                                    <span className="font-mono font-medium text-foreground tabular-nums">
                                      {`${(Number(value) * 100).toFixed(2)}%`}
                                    </span>
                                  </>
                                )}
                              />
                            }
                          />
                          <ChartLegend
                            content={<ChartLegendContent />}
                            verticalAlign="top"
                          />
                          <Line
                            dataKey="return"
                            type="monotone"
                            stroke="#82181a"
                            strokeWidth={2}
                            dot={false}
                            activeDot={{ r: 4 }}
                          />
                          <Line
                            dataKey="bench"
                            type="monotone"
                            stroke="#024a70"
                            fill="url(#benchGradient)"
                            strokeWidth={2}
                            dot={false}
                            activeDot={{ r: 4 }}
                          />
                        </LineChart>
                      </ChartContainer>
                    ) : (
                      <div className="flex h-80 items-center justify-center rounded-xl border border-dashed border-border/60 text-sm text-muted-foreground">
                        No return curve data available
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card className="border border-border/60">
                  <CardHeader>
                    <CardTitle>Backtest Parameters</CardTitle>
                    <CardDescription>
                      Current backtest task parameter configuration
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {Object.keys(params).length ? (
                      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                        {paramOrder
                          .filter((key) => params[key] !== undefined)
                          .map((key) => (
                            <div
                              key={key}
                              className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2"
                            >
                              <div className="text-xs tracking-wide text-muted-foreground">
                                {paramLabels[key]}
                              </div>
                              <div className="mt-1 font-medium break-all text-foreground">
                                {formatParamValue(params[key], key)}
                              </div>
                            </div>
                          ))}
                      </div>
                    ) : (
                      <div className="text-sm text-muted-foreground">
                        No parameter information available
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
