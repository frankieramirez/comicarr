import {
  useRef,
  type ClipboardEvent,
  type DragEvent,
  type FormEvent,
} from "react";
import {
  Attachment,
  AttachmentInfo,
  AttachmentPreview,
  AttachmentRemove,
  Attachments,
} from "@/components/ai-elements/attachments";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import type { PendingChatImage } from "@/types/chat";
import { ArrowUp, ImagePlus, Square } from "lucide-react";

const ACCEPTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;
const ACCEPTED_IMAGE_TYPE_SET = new Set<string>(ACCEPTED_IMAGE_TYPES);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_IMAGES = 4;

interface ChatComposerProps {
  value: string;
  images: PendingChatImage[];
  isSending: boolean;
  error?: string | null;
  onChange: (value: string) => void;
  onImagesChange: (images: PendingChatImage[]) => void;
  onSubmit: () => void;
  onStop: () => void;
  onValidationError: (message: string) => void;
}

export function ChatComposer({
  value,
  images,
  isSending,
  error,
  onChange,
  onImagesChange,
  onSubmit,
  onStop,
  onValidationError,
}: ChatComposerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = (incoming: File[]) => {
    const imageFiles = incoming.filter((file) =>
      ACCEPTED_IMAGE_TYPE_SET.has(file.type),
    );
    if (imageFiles.length !== incoming.length) {
      onValidationError("Choose JPEG, PNG, or WebP images.");
      return;
    }
    if (imageFiles.some((file) => file.size > MAX_IMAGE_BYTES)) {
      onValidationError("Each image must be 10 MB or smaller.");
      return;
    }
    if (images.length + imageFiles.length > MAX_IMAGES) {
      onValidationError("Attach up to four images per message.");
      return;
    }
    onImagesChange([
      ...images,
      ...imageFiles.map((file) => ({
        id: crypto.randomUUID(),
        file,
        previewUrl: URL.createObjectURL(file),
      })),
    ]);
  };

  const removeImage = (id: string) => {
    const image = images.find((item) => item.id === id);
    if (image) URL.revokeObjectURL(image.previewUrl);
    onImagesChange(images.filter((item) => item.id !== id));
  };

  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData.files);
    if (files.length > 0) addFiles(files);
  };

  const handleDrop = (event: DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isSending) addFiles(Array.from(event.dataTransfer.files));
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if ((value.trim() || images.length > 0) && !isSending) onSubmit();
  };

  return (
    <form
      onSubmit={handleSubmit}
      onDragOver={(event) => event.preventDefault()}
      onDrop={handleDrop}
      className="mx-auto w-full max-w-3xl"
    >
      <InputGroup
        data-disabled={isSending || undefined}
        className="rounded-xl bg-card shadow-lg shadow-background/40"
      >
        {images.length > 0 && (
          <InputGroupAddon align="block-start" className="border-b pb-2">
            <Attachments variant="inline" className="w-full">
              {images.map((image) => (
                <Attachment
                  key={image.id}
                  data={{
                    id: image.id,
                    type: "file",
                    filename: image.file.name,
                    mediaType: image.file.type,
                    url: image.previewUrl,
                  }}
                  onRemove={() => removeImage(image.id)}
                >
                  <AttachmentPreview />
                  <AttachmentInfo />
                  <AttachmentRemove label={`Remove ${image.file.name}`} />
                </Attachment>
              ))}
            </Attachments>
          </InputGroupAddon>
        )}
        <InputGroupTextarea
          value={value}
          disabled={isSending}
          aria-label="Message Chat"
          aria-invalid={Boolean(error)}
          placeholder="Ask about your library or attach a comic cover…"
          className="min-h-16 max-h-40"
          onChange={(event) => onChange(event.target.value)}
          onPaste={handlePaste}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSubmit(event);
            }
          }}
        />
        <InputGroupAddon align="block-end" className="pt-1">
          <input
            ref={fileInputRef}
            type="file"
            className="sr-only"
            accept={ACCEPTED_IMAGE_TYPES.join(",")}
            multiple
            disabled={isSending}
            onChange={(event) => {
              addFiles(Array.from(event.target.files || []));
              event.target.value = "";
            }}
          />
          <InputGroupButton
            type="button"
            size="icon-sm"
            aria-label="Attach images"
            disabled={isSending}
            onClick={() => fileInputRef.current?.click()}
          >
            <ImagePlus />
          </InputGroupButton>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            JPEG, PNG, or WebP · 10 MB max
          </span>
          {isSending ? (
            <InputGroupButton
              type="button"
              size="icon-sm"
              variant="destructive"
              aria-label="Stop response"
              className="ml-auto"
              onClick={onStop}
            >
              <Square />
            </InputGroupButton>
          ) : (
            <InputGroupButton
              type="submit"
              size="icon-sm"
              variant="default"
              aria-label="Send message"
              className="ml-auto"
              disabled={!value.trim() && images.length === 0}
            >
              <ArrowUp />
            </InputGroupButton>
          )}
        </InputGroupAddon>
      </InputGroup>
      <div className="mt-2 min-h-4 px-1 text-xs text-muted-foreground">
        {error || "Enter sends · Shift+Enter adds a line"}
      </div>
    </form>
  );
}
