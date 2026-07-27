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
import { createLocalId } from "@/lib/ids";
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
        id: createLocalId(),
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
        className="rounded-2xl bg-card shadow-lg shadow-background/40"
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
          placeholder="Ask about your library, or drop a cover to identify it"
          className="min-h-16 max-h-40 text-sm"
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
      <div className="mt-2 flex min-h-4 items-center justify-between gap-3 px-1">
        <span
          className={
            error
              ? "text-xs text-destructive"
              : "mono-meta hidden text-[10px] sm:inline"
          }
        >
          {error || "enter sends · shift+enter new line"}
        </span>
        <span className="mono-meta shrink-0 text-[10px]">
          jpeg · png · webp · 10 MB
        </span>
      </div>
    </form>
  );
}
