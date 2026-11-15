import { Panel } from "../components/ui";

/* Landing page for the general game link. Explicit /join and /display links
   never pass through here. */

function readCode(): string | null {
  const hash = window.location.hash.replace(/^#/, "");
  const hashQuery = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const fromHash = new URLSearchParams(hashQuery).get("code");
  const fromSearch = new URLSearchParams(window.location.search).get("code");
  const code = (fromSearch ?? fromHash)?.trim().toUpperCase();
  return code && /^[A-Z0-9]{4}$/.test(code) ? code : null;
}

export function HomeApp() {
  const code = readCode();
  const base = import.meta.env.BASE_URL;
  const link = (path: string) => `${base}${path}${code ? `?code=${code}` : ""}`;

  return (
    <div className="relative min-h-screen bg-lavender px-4 py-6">
      <div className="mx-auto w-full" style={{ maxWidth: 440 }}>
        <Panel className="px-6 py-8 text-center">
          <p className="kicker">Game Night</p>
          <h1 className="mt-3 font-script text-[clamp(54px,14vw,76px)] leading-[0.95] text-gold-display">
            Game Night
          </h1>
          <p className="mt-4 text-[14px] leading-relaxed text-plum-soft">
            {code
              ? `Session ${code}. Join from this phone as a player, or watch the audience screen.`
              : "Join from this phone as a player, or watch the audience screen."}
          </p>

          <div className="mt-8 grid gap-3">
            <a className="btn btn-primary" href={link("join/")}>
              Join as Player
            </a>
            <a className="btn" href={link("display/")}>
              Watch Game
            </a>
          </div>

          <p className="mt-7 text-[10px] uppercase tracking-[0.24em] text-plum-hush">
            <a className="underline decoration-gold/50 underline-offset-4" href={`${base}host/`}>
              Host dashboard
            </a>
          </p>
        </Panel>
      </div>
    </div>
  );
}
