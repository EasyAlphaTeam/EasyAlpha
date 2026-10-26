import {
  ChevronUpIcon,
  PickaxeIcon,
  HomeIcon,
  LibraryBigIcon,
  LogOutIcon,
} from "lucide-react"
import {
  HashRouter,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
} from "react-router"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar"
import { Avatar, AvatarImage } from "@/components/ui/avatar"
import { Progress } from "@/components/ui/progress"
import { AuthDialog } from "@/components/auth/auth-dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { FactorMiningPage } from "@/pages/factor-mining/factor-mining.tsx"
import { FactorLibraryPage } from "@/pages/factor-library/factor-library.tsx"
import { Button } from "@/components/ui/button.tsx"
import useUser from "@/hooks/use-user.ts"
import { useCreation } from "ahooks"
import { createAvatar } from "@dicebear/core"
import { glass } from "@dicebear/collection"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip.tsx"
import Logo from "@/assets/logo.png"
import { TOUR_STEP_IDS } from "@/lib/tour.tsx"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover.tsx"
import useConfig from "@/hooks/use-config.ts"

type RouteItem = {
  title: string
  description: string
  href: string
  icon: typeof HomeIcon
  id: string
}

const routeItems: RouteItem[] = [
  {
    title: "Factor Research",
    description: "AI-powered factor design and evaluation tool",
    href: "/",
    icon: PickaxeIcon,
    id: "menu-home",
  },
  {
    title: "Factor Library",
    description: "Manage your factor expressions",
    href: "/factor-library",
    icon: LibraryBigIcon,
    id: TOUR_STEP_IDS.MENU_FACTOR_LIBRARY,
  },
]

function AppSidebar() {
  const location = useLocation()
  const { open } = useSidebar()
  const { signInModalOpen, setSignInModalOpen, user, logout, isAuthenticated } =
    useUser()

  const avatar = useCreation(() => {
    return user
      ? createAvatar(glass, {
          seed: user.id,
          size: 36,
          // ... other options
        }).toDataUri()
      : ""
  }, [user])

  const creditsPercent = useCreation(() => (user ? user.credits : 0), [user])

  return (
    <>
      <Sidebar collapsible="icon">
        {open && (
          <SidebarHeader className="gap-3 p-3">
            <div className="flex items-center gap-3 rounded-xl px-3 py-3">
              {/*<div className="flex size-10 items-center justify-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground shadow-sm">*/}
              {/*  <BarChart3Icon className="size-5" />*/}
              {/*</div>*/}
              <div className="px-3">
                <img src={Logo} alt="logo" className="block h-auto w-full" />
                {/*<div className="truncate text-sm font-semibold">EasyAlpha</div>*/}
                {/*<div className="text-xs text-sidebar-foreground/70">*/}
                {/*  AI 因子研究工具*/}
                {/*</div>*/}
              </div>
            </div>
          </SidebarHeader>
        )}
        <SidebarContent>
          <SidebarGroup>
            {/*<SidebarGroupLabel>导航</SidebarGroupLabel>*/}
            <SidebarGroupContent>
              <SidebarMenu>
                {routeItems.map((item) => {
                  const Icon = item.icon

                  return (
                    <SidebarMenuItem key={item.href} id={item.id}>
                      <SidebarMenuButton
                        asChild
                        tooltip={item.title}
                        isActive={
                          item.href === "/"
                            ? location.pathname === item.href
                            : location.pathname.startsWith(item.href)
                        }
                      >
                        <NavLink
                          to={item.href}
                          end={item.href === "/"}
                          className="flex items-center gap-2"
                        >
                          <Icon />
                          <span>{item.title}</span>
                        </NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="p-3">
          {isAuthenticated && user ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                {open ? (
                  <SidebarMenuButton
                    tooltip={user.phone}
                    className="h-auto rounded-xl border border-sidebar-border bg-sidebar-accent/60 p-3"
                  >
                    <Avatar className="size-9 rounded-xl">
                      <AvatarImage src={avatar} />
                    </Avatar>
                    <div className="grid min-w-0 flex-1 text-left group-data-[collapsible=icon]:hidden">
                      <span className="truncate text-sm font-medium">
                        {user.phone}
                      </span>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-2 group-data-[collapsible=icon]:hidden">
                            <Progress
                              value={creditsPercent}
                              className="h-1.5 flex-1"
                            />
                            <span className="text-xs whitespace-nowrap text-sidebar-foreground/70">
                              {Math.round(creditsPercent)}%
                            </span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>剩余额度</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <ChevronUpIcon className="ml-auto group-data-[collapsible=icon]:hidden" />
                  </SidebarMenuButton>
                ) : (
                  <Avatar className="size-7 rounded-xl">
                    <AvatarImage src={avatar} />
                  </Avatar>
                )}
              </DropdownMenuTrigger>
              <DropdownMenuContent side="top" align="start" className="w-56">
                <DropdownMenuLabel className="flex items-center gap-2">
                  <Avatar className="size-8">
                    <AvatarImage src={avatar} />
                  </Avatar>
                  <div className="min-w-0">
                    <div className="truncate font-medium">{user.phone}</div>
                    {/*<div className="truncate text-xs text-muted-foreground">*/}
                    {/*  {user.phone || "mock.google@example.com"}*/}
                    {/*</div>*/}
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onClick={logout}>
                  <LogOutIcon />
                  退出登录
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Button size="lg" onClick={() => setSignInModalOpen(true)}>
              登录 / 注册
            </Button>
          )}
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
      <AuthDialog open={signInModalOpen} onOpenChange={setSignInModalOpen} />
    </>
  )
}

function AppHeader() {
  const location = useLocation()
  const currentRoute =
    routeItems.find((item) =>
      item.href === "/"
        ? location.pathname === item.href
        : location.pathname.startsWith(item.href)
    ) ?? routeItems[0]
  const { config } = useConfig()

  return (
    <header className="sticky top-0 z-20 flex items-center justify-between border-b border-border/70 bg-background/80 px-4 py-2 backdrop-blur md:px-6 md:py-3">
      <div className="flex items-center gap-3">
        <SidebarTrigger className="" />
        <div className="cursor-default text-sm font-semibold">
          {currentRoute.title}
        </div>
      </div>
    </header>
  )
}

function AppLayout() {
  return (
    <SidebarProvider defaultOpen>
      <AppSidebar />
      <SidebarInset className="h-svh overflow-hidden">
        <AppHeader />
        <div className="flex min-h-0 flex-1 flex-col p-4 md:p-6">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}

export function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<FactorMiningPage />} />
          <Route path="/factor-library" element={<FactorLibraryPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  )
}

export default App
