let hiddenByLauncher = false;
let hidden = computeHidden();

function computeHidden() {
  return hiddenByLauncher || document.visibilityState === "hidden";
}

function update() {
  const next = computeHidden();
  if (next === hidden) return;
  hidden = next;
  document.documentElement.classList.toggle("app-hidden", hidden);
}

document.documentElement.classList.toggle("app-hidden", hidden);
document.addEventListener("visibilitychange", update);

export function setAppHidden(value: boolean) {
  hiddenByLauncher = value;
  update();
}

export function isAppHidden() {
  return hidden;
}
