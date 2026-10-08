import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://docs.mimiq.tech',
  integrations: [
    starlight({
      title: 'Mimiq Docs',
      description: 'Copy trading and delta-neutral strategies across 11 perp DEXs. Non-custodial. Invite-only.',
      logo: { src: './src/assets/mimiq-mark.svg', alt: 'Mimiq' },
      favicon: '/favicon.svg',
      customCss: ['./src/styles/custom.css'],
      components: {
        Footer: './src/components/Footer.astro',
        SocialIcons: './src/components/SocialIcons.astro',
        ThemeSelect: './src/components/Empty.astro',
      },
      head: [
        { tag: 'script', content: "try{localStorage.setItem('starlight-theme','dark')}catch(e){};document.documentElement.dataset.theme='dark'" },
        { tag: 'meta', attrs: { name: 'theme-color', content: '#05090e' } },
        { tag: 'meta', attrs: { property: 'og:image', content: 'https://docs.mimiq.tech/og.png' } },
        { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
        { tag: 'meta', attrs: { name: 'twitter:image', content: 'https://docs.mimiq.tech/og.png' } },
      ],
      sidebar: [
        { label: 'Start', items: [
          { label: 'What is Mimiq', link: '/' },
          { label: 'Quickstart', link: '/start/quickstart/' },
          { label: 'Which mode?', link: '/start/which-mode/' },
        ]},
        { label: 'Using the bot', autogenerate: { directory: 'guide' } },
        { label: 'Concepts', items: [
          { label: 'Non-custodial and your keys', link: '/concepts/non-custodial/' },
        ]},
        { label: 'Fees', link: '/fees/' },
        { label: 'Sources', link: '/sources/' },
        { label: 'Venues', autogenerate: { directory: 'venues' } },
        { label: 'Trust', items: [
          { label: 'Security', link: '/security/' },
          { label: 'Privacy', link: '/privacy/' },
          { label: 'Risks', link: '/risks/' },
        ]},
        { label: 'Help', items: [
          { label: 'FAQ', link: '/faq/' },
          { label: 'Glossary', link: '/glossary/' },
        ]},
      ],
    }),
  ],
});
