import { useLocalStorage } from "@/hooks/use-local-storage";
import { CONTROLS_KEY } from "@/lib/constants/local-storage";
import { createContext, useContext } from "react";

interface ControlsContextType {
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

export const ControlsContext = createContext<ControlsContextType | null>(null);

export function ControlsProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useLocalStorage(CONTROLS_KEY, true);

  return (
    <ControlsContext.Provider value={{ open, setOpen }}>
      <div className="group/controls" data-expanded={open}>
        {children}
      </div>
    </ControlsContext.Provider>
  );
}

export function useControls() {
  const context = useContext(ControlsContext);

  if (!context) {
    throw new Error("useControls must be used within a ControlsProvider");
  }

  return context as ControlsContextType;
}
