/*
 * テーマ切替スクリプト。html要素の data-theme (light / dark) を切り替え、
 * localStorage に保存してページ間・再訪問でも維持する。未設定時はOSの配色設定に従う。
 * HTMLページが読み込めるscriptはこのファイルだけ (check_html.py の HTML002)。
 */
(() => {
  const root = document.documentElement;
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") {
    root.dataset.theme = stored;
  }

  const isDark = () => {
    if (root.dataset.theme) {
      return root.dataset.theme === "dark";
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  };

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.querySelector(".theme-toggle");
    if (button === null) {
      return;
    }
    const render = () => {
      button.textContent = isDark() ? "☀" : "🌙";
      button.setAttribute(
        "aria-label",
        isDark() ? "ライトテーマに切り替える" : "ダークテーマに切り替える",
      );
    };
    button.addEventListener("click", () => {
      const next = isDark() ? "light" : "dark";
      root.dataset.theme = next;
      localStorage.setItem("theme", next);
      render();
    });
    render();
  });
})();
