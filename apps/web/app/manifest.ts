import type { MetadataRoute } from "next";

/** Lets people install the dashboard as an app (desktop and phone). */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "STARK OS",
    short_name: "STARK OS",
    description: "Your AI social media team: seven agents that ask before they post.",
    start_url: "/",
    display: "standalone",
    background_color: "#06080b",
    theme_color: "#06080b",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }],
  };
}
