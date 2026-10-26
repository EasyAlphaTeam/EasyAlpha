import { Button } from "@/components/ui/button.tsx"
import { ArrowUpIcon } from "lucide-react"
import { useRequest } from "ahooks"
import { Spinner } from "@/components/ui/spinner.tsx"
import useUser from "@/hooks/use-user.ts"
import { toast } from "sonner"
import { TOUR_STEP_IDS } from "@/lib/tour.tsx"

type ComposerProps = {
  value: string
  onChange: (value: string) => void
  onSend: () => Promise<void>
  placeholder: string
  isStreaming?: boolean
}

export function MiningComposer({
  value,
  onChange,
  onSend,
  placeholder,
  isStreaming = false,
}: ComposerProps) {
  const { refreshUser, isAuthenticated, setSignInModalOpen } = useUser()

  const { runAsync, loading: sending } = useRequest(
    async () => {
      if (!isAuthenticated) {
        setSignInModalOpen(true)
        return
      }
      const user = await refreshUser()
      if (!user || user.credits < 10) {
        toast.info("Insufficient credits.")
        return
      }
      await onSend()
    },
    {
      manual: true,
    }
  )
  const loading = sending || isStreaming

  return (
    <div className="">
      <div
        id={TOUR_STEP_IDS.INPUT_MINING_DIRECTION}
        className="relative overflow-hidden rounded-2xl border border-border/70 bg-card px-3 py-3 shadow-sm"
      >
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          maxLength={1000}
          rows={2}
          disabled={loading}
          className="w-full resize-none text-sm leading-6 outline-none placeholder:text-muted-foreground"
        />
        <div className="flex justify-end">
          <Button
            type="button"
            size="icon"
            onClick={runAsync}
            disabled={!value.trim() || loading}
            className="rounded-full"
            id={TOUR_STEP_IDS.SEND_MAXING_DIRECTION}
          >
            {loading ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <ArrowUpIcon className="size-4" />
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}
