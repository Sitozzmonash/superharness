// @ts-check

const lightCodeTheme = require("prism-react-renderer").themes.github;
const darkCodeTheme = require("prism-react-renderer").themes.dracula;

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: "Super Harness",
  tagline: "A Python-native, provider-agnostic agent runtime",
  favicon: "img/favicon.svg",
  url: process.env.DOCS_URL || "https://super-harness.github.io",
  baseUrl: process.env.DOCS_BASE_URL || "/super-harness/",
  organizationName: process.env.GITHUB_ORG || "super-harness",
  projectName: process.env.GITHUB_REPO || "super-harness",
  onBrokenLinks: "throw",
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: "throw",
    },
  },
  i18n: {
    defaultLocale: "en",
    locales: ["en"],
  },
  presets: [
    [
      "classic",
      {
        docs: {
          routeBasePath: "/",
          sidebarPath: require.resolve("./sidebars.js"),
          editUrl: undefined,
        },
        blog: false,
        theme: {
          customCss: require.resolve("./src/css/custom.css"),
        },
      },
    ],
  ],
  themeConfig: {
    navbar: {
      title: "Super Harness",
      items: [
        { to: "/get-started", label: "Get Started", position: "left" },
        { to: "/user-guide", label: "User Guide", position: "left" },
        { to: "/internals", label: "Internals", position: "left" },
        { to: "/examples", label: "Examples", position: "left" },
        { to: "/api-reference", label: "API", position: "left" },
        { to: "/ecosystem", label: "Ecosystem", position: "left" },
        { to: "/compatibility", label: "Testing", position: "left" },
        { to: "/troubleshooting", label: "Troubleshooting", position: "left" },
      ],
    },
    footer: {
      style: "dark",
      copyright: `Copyright © ${new Date().getFullYear()} Super Harness contributors.`,
    },
    prism: {
      theme: lightCodeTheme,
      darkTheme: darkCodeTheme,
    },
  },
};

module.exports = config;
