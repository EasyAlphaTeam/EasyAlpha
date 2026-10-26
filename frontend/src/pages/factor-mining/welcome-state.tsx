import { MiningComposer } from "@/pages/factor-mining/mining-composer.tsx"
import { useState } from "react"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card.tsx"
import Logo from "@/assets/logo.png"
import { TOUR_STEP_IDS } from "@/lib/tour.tsx"

type WelcomeStateProps = {
  onSend: (content: string) => Promise<void>
}

export function WelcomeState({ onSend }: WelcomeStateProps) {
  const [input, setInput] = useState("")

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mx-auto flex max-w-4xl flex-1 items-center justify-center px-4 pt-6 pb-8 md:px-8">
        <div className="flex w-full max-w-4xl cursor-default flex-col gap-8">
          <div className="space-y-3 text-center">
            <img src={Logo} alt="logo" className="block h-auto w-60" />
            <p className="text-sm font-medium text-muted-foreground md:text-base">
              AI-powered factor design and evaluation tool. Input your research
            </p>
          </div>
        </div>
      </div>

      <div className="mx-auto w-full max-w-4xl">
        <div
          id={TOUR_STEP_IDS.MINING_DIRECTION_EXAMPLES}
          className="mb-4 grid gap-3 md:grid-cols-3"
        >
          {examplePrompts.map((e) => (
            <Card
              key={e.title}
              size="sm"
              onClick={() => setInput(e.content)}
              className="cursor-pointer transition hover:opacity-75"
            >
              <CardHeader>
                <CardTitle>{e.title}</CardTitle>
              </CardHeader>
              <CardContent>{e.content}</CardContent>
            </Card>
          ))}
        </div>
        <MiningComposer
          value={input}
          onChange={setInput}
          onSend={async () => {
            await onSend(input)
            setInput("")
          }}
          placeholder="Enter factor research objective"
        />
      </div>
    </div>
  )
}
