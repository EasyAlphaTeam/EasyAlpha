import { createRoot } from "react-dom/client"
import { SingletonHooksContainer } from "react-singleton-hook"
import DisableDevtool from "disable-devtool"
import "./index.css"
import App from "./App.tsx"
import { ThemeProvider } from "@/components/theme-provider.tsx"
import { TooltipProvider } from "@/components/ui/tooltip.tsx"
import { Toaster } from "@/components/ui/sonner.tsx"
import { TourProvider } from "@/components/ui/tour.tsx"

if (import.meta.env.MODE !== "development") {
  DisableDevtool({
    md5: "da752c10e94d7b7b0344621c1beb4304",
    disableMenu: false,
  })
}

createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <Toaster />
    <TourProvider>
      <TooltipProvider>
        <SingletonHooksContainer />
        <App />
      </TooltipProvider>
    </TourProvider>
  </ThemeProvider>
)
