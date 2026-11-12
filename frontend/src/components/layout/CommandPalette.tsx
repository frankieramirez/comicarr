import {
  useEffect,
  useMemo,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import {
  Activity,
  BookOpen,
  Calendar,
  FolderInput,
  LayoutDashboard,
  ListTodo,
  Plus,
  Search,
  Settings,
} from "lucide-react";
import { CoverCell } from "@/components/data-table/cells/CoverCell";
import { Kbd } from "@/components/ui/kbd";
import { useSeries } from "@/hooks/useSeries";
import { OPEN_PALETTE_EVENT } from "@/lib/commandPalette";

const SERIES_LIMIT = 5;

const PAGES: { label: string; to: string; kbd: string; icon: ReactNode }[] = [
  { label: "Dashboard", to: "/", kbd: "G D", icon: <LayoutDashboard /> },
  { label: "Library", to: "/library", kbd: "G L", icon: <BookOpen /> },
  { label: "Wanted", to: "/wanted", kbd: "G W", icon: <ListTodo /> },
  { label: "Releases", to: "/releases", kbd: "G R", icon: <Calendar /> },
  { label: "Activity", to: "/activity", kbd: "G Y", icon: <Activity /> },
  { label: "Import", to: "/import", kbd: "G I", icon: <FolderInput /> },
  { label: "Settings", to: "/settings", kbd: "G S", icon: <Settings /> },
];

interface Item {
  id: string;
  section: "Series" | "Actions" | "Go to";
  label: string;
  to: string;
  icon: ReactNode;
  meta?: ReactNode;
}

/**
 * ⌘K: one box that finds a series, starts the obvious action for it, or
 * jumps to a page. Series come from the library already in the query cache,
 * so typing never waits on the network.
 */
export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const { data: series = [] } = useSeries();

  useEffect(() => {
    const onOpen = () => {
      setQuery("");
      setActive(0);
      setOpen(true);
    };
    window.addEventListener(OPEN_PALETTE_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_PALETTE_EVENT, onOpen);
  }, []);

  const items = useMemo<Item[]>(() => {
    const needle = query.trim().toLowerCase();
    const matches = needle
      ? series
          .filter((s) => s.ComicName.toLowerCase().includes(needle))
          .sort(
            (a, b) =>
              Number(!a.ComicName.toLowerCase().startsWith(needle)) -
                Number(!b.ComicName.toLowerCase().startsWith(needle)) ||
              a.ComicName.localeCompare(b.ComicName),
          )
          .slice(0, SERIES_LIMIT)
      : [];

    const seriesItems: Item[] = matches.map((s) => ({
      id: `series:${s.ComicID}`,
      section: "Series",
      label: s.ComicName,
      to: `/library/${s.ComicID}`,
      icon: (
        <span className="[&>div]:h-6 [&>div]:w-[18px] [&>div]:rounded-sm">
          <CoverCell comicId={s.ComicID} />
        </span>
      ),
      meta:
        s.Total != null ? (
          <span className="mono-meta">
            {s.Have ?? 0} / {s.Total}
          </span>
        ) : undefined,
    }));

    const actions: Item[] = needle
      ? [
          {
            id: "add",
            section: "Actions",
            label: `Add a series matching “${query.trim()}”`,
            to: `/search?q=${encodeURIComponent(query.trim())}&page=1`,
            icon: <Plus />,
          },
        ]
      : [
          {
            id: "search-wanted",
            section: "Actions",
            label: "Review Wanted issues",
            to: "/wanted",
            icon: <Search />,
          },
        ];

    const pages: Item[] = PAGES.filter(
      (p) => !needle || p.label.toLowerCase().includes(needle),
    ).map((p) => ({
      id: `page:${p.to}`,
      section: "Go to",
      label: p.label,
      to: p.to,
      icon: p.icon,
      meta: <Kbd className="font-mono text-[10px]">{p.kbd}</Kbd>,
    }));

    return [...seriesItems, ...actions, ...pages];
  }, [query, series]);

  const choose = (item: Item | undefined) => {
    if (!item) return;
    setOpen(false);
    navigate(item.to);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, items.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(items[active]);
    }
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop className="fixed inset-0 z-50 bg-black/60 transition-opacity data-starting-style:opacity-0 data-ending-style:opacity-0" />
        <DialogPrimitive.Popup
          aria-label="Command palette"
          className="fixed left-1/2 top-[12vh] z-50 w-[min(640px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-xl border border-border-strong bg-surface-1 shadow-2xl transition-[opacity,transform] duration-150 data-starting-style:scale-[0.98] data-starting-style:opacity-0 data-ending-style:opacity-0"
        >
          <div className="flex items-center gap-3 border-b border-border-subtle px-4 py-3">
            <Search className="size-4 shrink-0 text-muted-foreground" />
            <input
              autoFocus
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              placeholder="Find a series, run an action, or go to a page"
              aria-label="Command palette search"
              role="combobox"
              aria-expanded="true"
              aria-controls="command-palette-list"
              aria-activedescendant={
                items[active] ? `palette-${items[active].id}` : undefined
              }
              className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-muted-foreground"
            />
            <Kbd className="font-mono text-[10px]">esc</Kbd>
          </div>

          <ul
            id="command-palette-list"
            role="listbox"
            aria-label="Results"
            className="max-h-[56vh] overflow-auto p-1.5"
          >
            {items.map((item, index) => (
              <PaletteRow
                key={item.id}
                item={item}
                index={index}
                active={index === active}
                showSection={
                  index === 0 || items[index - 1].section !== item.section
                }
                onHover={() => setActive(index)}
                onChoose={() => choose(item)}
              />
            ))}
          </ul>

          <div className="flex items-center gap-4 border-t border-border-subtle px-4 py-2 text-[12px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Kbd className="font-mono text-[10px]">↑↓</Kbd> to move
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd className="font-mono text-[10px]">↵</Kbd> to open
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd className="font-mono text-[10px]">⌘K</Kbd> anywhere
            </span>
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function PaletteRow({
  item,
  index,
  active,
  showSection,
  onHover,
  onChoose,
}: {
  item: Item;
  index: number;
  active: boolean;
  showSection: boolean;
  onHover: () => void;
  onChoose: () => void;
}) {
  return (
    <>
      {showSection && (
        <li
          role="presentation"
          className={`px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground ${index === 0 ? "pt-1.5" : "pt-3"}`}
        >
          {item.section}
        </li>
      )}
      <li
        id={`palette-${item.id}`}
        role="option"
        aria-selected={active}
        onMouseMove={onHover}
        onClick={onChoose}
        className={`flex h-10 cursor-pointer items-center gap-3 rounded-lg px-2.5 text-[13px] ${
          active ? "bg-surface-3 text-foreground" : "text-foreground-2"
        }`}
      >
        <span className="flex size-5 shrink-0 items-center justify-center text-muted-foreground [&>svg]:size-4">
          {item.icon}
        </span>
        <span className="min-w-0 flex-1 truncate">{item.label}</span>
        {item.meta}
      </li>
    </>
  );
}
