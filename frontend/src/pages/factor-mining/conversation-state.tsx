import { useEffect, useRef, useState } from "react"
import { ChevronRightIcon, InfoIcon } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area.tsx"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx"
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card.tsx"
import { Separator } from "@/components/ui/separator.tsx"
import { cn } from "@/lib/utils.ts"
import { Streamdown } from "streamdown"
import { MiningComposer } from "@/pages/factor-mining/mining-composer.tsx"
import { useChatEventStream } from "@/hooks/use-chat-event-stream.ts"
import { useMemoizedFn } from "ahooks"
import { Spinner } from "@/components/ui/spinner.tsx"
import { Button } from "@/components/ui/button.tsx"

type ConversationProps = {
  chatId: string
}


function formatMetricValue(metricKey: string, rawValue?: string) {
  if (rawValue == null || rawValue === "") {
    return "--"
  }

  const value = Number(rawValue)
  if (!Number.isFinite(value)) {
    return rawValue
  }

  if (metricKey === "Annual Return" || metricKey === "Max Drawdown") {
    return `${(value * 100).toFixed(2)}%`
  }

  return value.toFixed(4)
}

function getSignedMetricClassname(rawValue?: string) {
  const value = Number(rawValue)
  if (!Number.isFinite(value)) {
    return "text-foreground"
  }

  if (value > 0) {
    return "text-red-600"
  }

  if (value < 0) {
    return "text-emerald-600"
  }

  return "text-foreground"
}

function getGradedMetricClassname(metricKey: string, rawValue?: string) {
  const value = Number(rawValue)
  if (!Number.isFinite(value)) {
    return "text-foreground"
  }

  const absValue = Math.abs(value)

  const thresholds =
    metricKey === "IC Mean" || metricKey === "Rank IC Mean"
      ? [0.08, 0.05, 0.03, 0.01]
      : [1.2, 0.8, 0.5, 0.2]

  if (absValue >= thresholds[0]) {
    return "text-red-600"
  }

  if (absValue >= thresholds[1]) {
    return "text-orange-600"
  }

  if (absValue >= thresholds[2]) {
    return "text-amber-600"
  }

  if (absValue >= thresholds[3]) {
    return "text-lime-600"
  }

  return "text-emerald-600"
}

function getMetricValueClassname(
  metricKey: string,
  tone: "signed" | "graded",
  rawValue?: string
) {
  if (tone === "signed") {
    return getSignedMetricClassname(rawValue)
  }

  return getGradedMetricClassname(metricKey, rawValue)
}

function MetricItem({
  metricKey,
  label,
  value,
  tone,
  description,
}: {
  metricKey: string
  label: string
  value?: string | number
  tone: "signed" | "graded"
  description: string
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-muted/30 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium tracking-wide text-muted-foreground">
          {label}
        </div>
        <HoverCard openDelay={120} closeDelay={80}>
          <HoverCardTrigger asChild>
            <button
              type="button"
              className="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              aria-label={`${label}`}
            >
              <InfoIcon className="size-3.5" />
            </button>
          </HoverCardTrigger>
          <HoverCardContent
            side="top"
            align="center"
            className="w-72 space-y-1.5 p-3"
          >
            <div className="text-sm font-medium text-foreground">{label}</div>
            <div className="text-sm leading-6 text-muted-foreground">
              {description}
            </div>
          </HoverCardContent>
        </HoverCard>
      </div>
      <div
        className={cn(
          "mt-2 text-2xl font-semibold tracking-tight",
          getMetricValueClassname(metricKey, tone, value)
        )}
      >
        {formatMetricValue(metricKey, value)}
      </div>
    </div>
  )
}

function renderConversationMessage(
  message: API.Message,
  isLastMessage?: boolean
) {
  return message.type === "backtest" ? (
    isLastMessage ? (
      <div className="flex items-center gap-2 px-3">
        <Spinner data-icon="inline-start" />
        <span>Factor backtesting...</span>
      </div>
    ) : null
  ) : message.type === "factor" ? (
    message.factor.expr ? (
      <>
        <Card
          key={message.id}
          className="cursor-default border border-border/60 shadow-sm"
        >
          <CardHeader className="gap-3">
            <div className="space-y-1">
              <CardTitle className="flex items-center">
                Factor
                <div className="mr-2 ml-1 rounded-md border border-border bg-secondary px-1 py-0.5 text-sm">
                  {message.factor.index}
                </div>
                <a href="#/factor-library">
                  <Button size="sm">
                    Go to Factor Library
                    <ChevronRightIcon />
                  </Button>
                </a>
              </CardTitle>
            </div>

            <div className="rounded-xl border border-border/60 bg-muted/40 p-4">
              <div className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {message.factor.name || "--"}
              </div>
              <code className="block font-mono text-[13px] leading-6 break-all whitespace-pre-wrap text-foreground">
                {message.factor.expr || "--"}
              </code>
            </div>
          </CardHeader>

          <Separator />

          <CardContent>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
              {BACKTEST_METRICS.map((metric) => (
                <MetricItem
                  key={metric.key}
                  metricKey={metric.key}
                  label={metric.label}
                  value={message.factor.backtest_result[metric.key]}
                  tone={metric.tone}
                  description={metric.description}
                />
              ))}
            </div>
          </CardContent>
        </Card>
        {isLastMessage && (
          <div className="flex items-center gap-2 px-3">
            <Spinner data-icon="inline-start" />
            <span>AI is evaluating the factor</span>
          </div>
        )}
      </>
    ) : null
  ) : (
    <div
      key={message.id}
      className={
        message.type === "ai"
          ? "w-full px-3 py-3"
          : "ml-auto w-fit rounded-xl bg-card px-4 py-2 text-primary-foreground"
      }
    >
      <Streamdown className="text-sm leading-7" parseIncompleteMarkdown>
        {message.content}
      </Streamdown>
    </div>
  )
}

export function ConversationState({ chatId }: ConversationProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  const [autoScroll, setAutoScroll] = useState(true)
  const [input, setInput] = useState("")
  const { messages, streamMessages, isStreaming, sendMessage } =
    useChatEventStream(chatId)

  const scrollToBottom = useMemoizedFn(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "auto",
      block: "end",
    })
  })

  useEffect(() => {
    if (autoScroll) {
      scrollToBottom()
    }
  }, [messages, streamMessages, scrollToBottom, autoScroll])

  const handleScroll = (e: any) => {
    const { scrollTop, scrollHeight, clientHeight } = e.target
    const isAtBottom = scrollTop + clientHeight >= scrollHeight - 10

    setAutoScroll(isAtBottom)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-hidden">
        <ScrollArea className="h-full" onScroll={handleScroll}>
          <div className="mx-auto flex min-h-full w-full max-w-4xl flex-col gap-4 py-6">
            {messages.map((e) => renderConversationMessage(e))}
            {isStreaming && streamMessages.length === 0 && (
              <div className="flex items-center gap-2 px-3">
                <Spinner data-icon="inline-start" />
                <span>AI is designing the factor</span>
              </div>
            )}
            {streamMessages.map((e, i) =>
              renderConversationMessage(e, i === streamMessages.length - 1)
            )}
          </div>
          <div ref={bottomRef} className="h-0" />
          <div className="absolute right-0 bottom-0 left-0 h-10 bg-linear-to-t from-[#0a0a0a] to-transparent"></div>
        </ScrollArea>
      </div>

      <div className="mx-auto w-full max-w-4xl px-4 md:px-0">
        <MiningComposer
          value={input}
          onChange={setInput}
          onSend={async () => {
            const content = input.trim()
            if (!content) return
            setInput("")
            await sendMessage(content)
          }}
          placeholder=""
          isStreaming={isStreaming}
        />
      </div>
    </div>
  )
}
