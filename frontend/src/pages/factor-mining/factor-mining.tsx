import { useEffect, useState } from "react"
import { PlusIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils.ts"
import { WelcomeState } from "@/pages/factor-mining/welcome-state.tsx"
import { ConversationState } from "@/pages/factor-mining/conversation-state.tsx"
import useChats from "@/hooks/use-chats.ts"
import { useMemoizedFn } from "ahooks"
import { TourAlertDialog, useTour } from "@/components/ui/tour.tsx"
import { startSteps, TOUR_STORAGE_KEY } from "@/lib/tour.tsx"

export function FactorMiningPage() {
  const { setSteps, isTourCompleted } = useTour()
  const { chatThreads, createChat } = useChats()
  const [activeChatId, setActiveChatId] = useState<string | null>(null)
  const [openTour, setOpenTour] = useState(false)

  const handleCreateChat = useMemoizedFn(async (content: string) => {
    const chat = await createChat(content)
    await new Promise((resolve) => setTimeout(resolve, 500))
    setActiveChatId(chat?.id ?? "")
  })

  useEffect(() => {
    setSteps(startSteps)
    const timer = setTimeout(() => {
      if (!localStorage.getItem(TOUR_STORAGE_KEY.START)) {
        setOpenTour(true)
      }
    }, 500)
    return () => {
      clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    if (isTourCompleted) {
      localStorage.setItem(TOUR_STORAGE_KEY.START, "1")
    }
  }, [isTourCompleted])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col rounded-3xl border border-border/60 bg-card/90">
          <div className="border-b border-border/60 p-4">
            <Button
              size="lg"
              variant="outline"
              className="w-full"
              onClick={() => setActiveChatId("")}
            >
              <PlusIcon />
              新建挖掘
            </Button>
          </div>

          <div className="min-h-0 flex-1 px-4 pt-3 pb-4">
            <div className="mb-2 cursor-default px-1 text-xs font-medium tracking-wide text-muted-foreground">
              挖掘历史
            </div>
            <ScrollArea className="h-[calc(100%-1rem)] w-full [&>div>div]:block!">
              <div className="flex w-full min-w-0 flex-col gap-2">
                {chatThreads.map((thread) => {
                  const isActive = thread.id === activeChatId

                  return (
                    <div
                      key={thread.id}
                      onClick={() => setActiveChatId(thread.id)}
                      className={cn(
                        "w-full cursor-pointer truncate rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors",
                        isActive ? "bg-muted" : "hover:bg-muted"
                      )}
                    >
                      {thread.title}
                    </div>
                  )
                })}
              </div>
            </ScrollArea>
          </div>
        </div>

        <div className="min-h-0">
          {activeChatId ? (
            <ConversationState chatId={activeChatId} />
          ) : (
            <WelcomeState onSend={handleCreateChat} />
          )}
        </div>
      </div>
      <TourAlertDialog
        isOpen={openTour}
        setIsOpen={setOpenTour}
        title="欢迎使用 EasyAlpha"
        description="快速浏览，了解 EasyAlpha 的核心功能与使用方式"
        onSkip={() => {
          localStorage.setItem(TOUR_STORAGE_KEY.START, "1")
        }}
      />
    </div>
  )
}
