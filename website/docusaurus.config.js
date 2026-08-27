// @ts-check

const lightCodeTheme = require("prism-react-renderer").themes.github;
const darkCodeTheme = require("prism-react-renderer").themes.dracula;

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: "Super Harness",
  tagline: "A Python-native, provider-agnostic agent runtime",
  favicon: "img/favicon.svg",
  // GitHub Pages project sites are served below `/<repository>/`.
  // These defaults match the public Sitozzmonash/superharness repository;
  // environment variables retain support for forks and custom deployments.
  url: process.env.DOCS_URL || "https://sitozzmonash.github.io",
  baseUrl: process.env.DOCS_BASE_URL || "/superharness/",
  organizationName: process.env.GITHUB_ORG || "Sitozzmonash",
  projectName: process.env.GITHUB_REPO || "superharness",
  onBrokenLinks: "throw",
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: "throw",
    },
  },
  i18n: {
    defaultLocale: "zh-CN",
    locales: ["zh-CN", "en"],
    localeConfigs: {
      "zh-CN": { label: "简体中文", htmlLang: "zh-CN" },
      en: { label: "English", htmlLang: "en" },
    },
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
        { type: "doc", docId: "guide/guide-part1-start", label: "User Guide", position: "left" },
        { type: "doc", docId: "internals/internals-architecture", label: "Internals", position: "left" },
        { to: "/examples", label: "Examples", position: "left" },
        { to: "/api-reference", label: "API", position: "left" },
        { to: "/ecosystem", label: "Ecosystem", position: "left" },
        { to: "/compatibility", label: "Testing", position: "left" },
        { to: "/troubleshooting", label: "Troubleshooting", position: "left" },
        { type: "localeDropdown", position: "right" },
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