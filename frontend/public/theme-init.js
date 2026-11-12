// Sets the theme class before the first paint. It lives in its own file
// because the app's Content-Security-Policy allows no inline scripts.
(function () {
  let saved = null;
  try {
    saved = localStorage.getItem("comicarr-theme");
  } catch (e) {}
  const theme =
    saved === "light" || saved === "dark"
      ? saved
      : window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
  document.documentElement.classList.add(theme);
})();
