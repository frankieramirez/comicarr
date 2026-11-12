export default function CoverWall({ tiles }: { tiles: number }) {
  // Always draw enough tiles to cover a large screen, repeating the
  // picked covers so a small library still fills it.
  const slots = Array.from({ length: 72 }, (_, i) =>
    tiles > 0 ? i % tiles : 0,
  );
  return (
    <div
      aria-hidden="true"
      data-testid="cover-wall"
      className="pointer-events-none absolute inset-0 overflow-hidden"
    >
      <div className="grid -m-4 grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-3 p-4 md:gap-4 md:grid-cols-[repeat(auto-fill,minmax(140px,1fr))]">
        {slots.map((slot, index) => (
          <img
            key={index}
            src={`/api/auth/cover-wall/${slot}`}
            alt=""
            loading="lazy"
            className="aspect-[2/3] w-full rounded-md object-cover saturate-[0.8]"
            onError={(event) => {
              event.currentTarget.style.visibility = "hidden";
            }}
          />
        ))}
      </div>
      {/* Dim the wall so the card reads first, in both themes. */}
      <div
        className="absolute inset-0"
        style={{
          background: "color-mix(in srgb, var(--background) 92%, transparent)",
        }}
      />
    </div>
  );
}
