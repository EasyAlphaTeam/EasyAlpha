import { useEffect, useState } from "react"
import { Card, CardContent } from "@/components/ui/card.tsx"
import { InfoIcon } from "lucide-react"
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card.tsx"
import { Input } from "@/components/ui/input.tsx"
import { Button } from "@/components/ui/button.tsx"
import { cn } from "@/lib/utils.ts"
import { toast } from "sonner"
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table.tsx"
import useFactors from "@/hooks/use-factors.ts"
import { BacktestDetailDialog } from "./backtest-detail-dialog.tsx"
import useUser from "@/hooks/use-user.ts"

type MetricTone = "signed" | "graded"

const formatMetricValue = (metricKey: string, rawValue?: number) => {
  if (rawValue == null || Number.isNaN(rawValue)) {
    return "--"
  }

  if (metricKey === "Annual Return" || metricKey === "Max Drawdown") {
    return `${(rawValue * 100).toFixed(2)}%`
  }

  return rawValue.toFixed(4)
}

const getSignedMetricClassname = (rawValue?: number) => {
  if (rawValue == null || Number.isNaN(rawValue)) {
    return "text-foreground"
  }

  if (rawValue > 0) {
    return "text-red-600"
  }

  if (rawValue < 0) {
    return "text-emerald-600"
  }

  return "text-foreground"
}

const getGradedMetricClassname = (metricKey: string, rawValue?: number) => {
  if (rawValue == null || Number.isNaN(rawValue)) {
    return "text-foreground"
  }

  const absValue = Math.abs(rawValue)
  const thresholds =
    metricKey === "IC Mean" || metricKey === "Rank IC Mean"
      ? [0.08, 0.05, 0.03, 0.01]
      : [1.2, 0.8, 0.5, 0.2]

  if (absValue >= thresholds[0]) return "text-red-600"
  if (absValue >= thresholds[1]) return "text-orange-600"
  if (absValue >= thresholds[2]) return "text-amber-600"
  if (absValue >= thresholds[3]) return "text-lime-600"

  return "text-emerald-600"
}

const getMetricValueClassname = (
  metricKey: string,
  tone: MetricTone,
  rawValue?: number
) => {
  if (tone === "signed") {
    return getSignedMetricClassname(rawValue)
  }

  return getGradedMetricClassname(metricKey, rawValue)
}

const copyExpression = async (expression: string) => {
  try {
    await navigator.clipboard.writeText(expression)
    toast.success("Copied to clipboard")
  } catch {
    toast.error("Failed to copy to clipboard")
  }
}

const metricColumn = (
  metricKey: string,
  header: string,
  tone: MetricTone
): ColumnDef<API.FactorRecord> => ({
  id: metricKey,
  header: () => (
    <div className="flex items-center justify-end gap-1.5 text-right">
      <span>{header}</span>
      <HoverCard openDelay={120} closeDelay={80}>
        <HoverCardTrigger asChild>
          <button
            type="button"
            className="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label={`${header} Metric Description`}
          >
            <InfoIcon className="size-3.5" />
          </button>
        </HoverCardTrigger>
        <HoverCardContent
          side="top"
          align="center"
          className="w-72 space-y-1.5 p-3"
        >
          <div className="text-sm font-medium text-foreground">{header}</div>
          <div className="text-sm leading-6 text-muted-foreground">
            {METRIC_DESCRIPTIONS[metricKey] ?? `${header} Metric Description`}
          </div>
        </HoverCardContent>
      </HoverCard>
    </div>
  ),
  cell: ({ row }) => {
    const value = row.original.backtest_result?.[metricKey]

    return (
      <div
        className={cn(
          "text-right font-medium tabular-nums",
          getMetricValueClassname(metricKey, tone, value)
        )}
      >
        {formatMetricValue(metricKey, value)}
      </div>
    )
  },
})

const createFactorColumns = ({
  onOpenDetail,
}: {
  onOpenDetail: (factorId: string) => void
}): ColumnDef<API.FactorRecord>[] => [
  {
    accessorKey: "index",
    header: "#",
  },
  {
    accessorKey: "name",
    header: "Factor",
  },
  {
    accessorKey: "expr",
    header: "Expression",
    cell: ({ row }) => {
      const expression = row.original.expr

      return (
        <HoverCard openDelay={120} closeDelay={80}>
          <HoverCardTrigger asChild>
            <button
              type="button"
              className="block max-w-[17rem] cursor-pointer rounded-md bg-muted px-2 py-1 text-left"
              onClick={() => {
                void copyExpression(expression)
              }}
            >
              <code className="block truncate text-xs text-muted-foreground">
                {expression}
              </code>
            </button>
          </HoverCardTrigger>
          <HoverCardContent side="top" align="start" className="w-96 p-3">
            <div className="space-y-1">
              <div className="text-xs font-medium tracking-wide text-muted-foreground">
                Factor Expression (Click to Copy)
              </div>
              <code className="block text-xs leading-6 break-all whitespace-pre-wrap text-foreground">
                {expression}
              </code>
            </div>
          </HoverCardContent>
        </HoverCard>
      )
    },
  },
  metricColumn("Annual Return", "Annual Return", "signed"),
  metricColumn("Information Ratio", "Information Ratio", "signed"),
  metricColumn("Max Drawdown", "Max Drawdown", "signed"),
  metricColumn("IC Mean", "IC Mean", "graded"),
  metricColumn("ICIR", "ICIR", "graded"),
  metricColumn("Rank IC Mean", "Rank IC Mean", "graded"),
  metricColumn("Rank ICIR", "Rank ICIR", "graded"),
  {
    accessorKey: "operation",
    header: "Operation",
    cell: ({ row }) => (
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onOpenDetail(row.original.id)}
        >
          Details
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => toast.info("Coming soon")}
        >
          Backtest
        </Button>
      </div>
    ),
  },
]

function DataTable<TData, TValue>({
  columns,
  data,
}: {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
}) {
  const { isAuthenticated, setSignInModalOpen } = useUser()

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <div className="table-sticky relative h-[calc(100vh-9rem)] overflow-y-auto rounded-2xl border border-border/60 bg-card">
      <Table>
        <TableHeader className="sticky! top-0 bg-background">
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow
              key={headerGroup.id}
              className="bg-muted/30 hover:bg-muted/30"
            >
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id} className="h-12 px-4">
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className="px-4 py-3">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="h-24 text-center text-muted-foreground"
              >
                {isAuthenticated ? (
                  "No data available"
                ) : (
                  <>
                    <div className="mb-1">Please sign in to view</div>
                    <Button onClick={() => setSignInModalOpen(true)}>
                      Sign In / Register
                    </Button>
                  </>
                )}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  )
}

export function FactorLibraryPage() {
  const { factors, refreshFactors } = useFactors()
  const [detailOpen, setDetailOpen] = useState(false)
  const [selectedFactorId, setSelectedFactorId] = useState<string>()

  const factorColumns = createFactorColumns({
    onOpenDetail: (factorId) => {
      setSelectedFactorId(factorId)
      setDetailOpen(true)
    },
  })

  useEffect(() => {
    refreshFactors()
  }, [])

  return (
    <div className="flex flex-1 flex-col gap-4">
      <Card className="border-border/60 bg-card/92">
        <CardContent className="space-y-4">
          <DataTable columns={factorColumns} data={factors} />
        </CardContent>
      </Card>
      <BacktestDetailDialog
        open={detailOpen}
        onOpenChange={setDetailOpen}
        factorId={selectedFactorId}
      />
    </div>
  )
}
