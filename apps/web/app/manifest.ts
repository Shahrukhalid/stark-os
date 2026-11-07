import type { MetadataRoute } from "next";

export const dynamic = "force-static"; // also works in the static export used by the desktop app

/** Lets people install the dashboard as an app (desktop and phone). */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "STARK AI",
    short_name: "STARK AI",
    description: "Your AI social media team: Vision, Wanda and seven agents that ask before they post.",
    start_url: "/",
    display: "standalone",
    background_color: "#06080b",
    theme_color: "#06080b",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }],
  };
}
