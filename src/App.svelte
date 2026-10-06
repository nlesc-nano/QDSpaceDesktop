<script>
  import Header from './Header.svelte';
  import Home from './Home.svelte';
  import About from './About.svelte';
  import Contact from './Contact.svelte';
  import Builder from './Builder.svelte';
  import Library from './Library.svelte';
  import Predict from './Predict.svelte';
  import { onMount } from 'svelte';
  import { isDesktopApp } from './lib/desktop.js';
  import { startCatalogRefresh } from './lib/remoteLibrary.js';

  let currentRoute = $state('home');
  const desktop = isDesktopApp();

  // Desktop: refresh the Library catalog from quantumdotspace.org in the background
  // (bundled copy stays the offline fallback). Never blocks the UI.
  onMount(() => {
    if (desktop) startCatalogRefresh();
  });

  // Library -> Builder hand-off (open a library structure in post-treatment)
  let builderHandoff = $state(null);
  function openInBuilder(handoff) {
    builderHandoff = handoff;
    currentRoute = 'builder';
  }
</script>

<div class="min-h-screen bg-slate-50 text-slate-900 flex flex-col">
  <Header bind:currentRoute={currentRoute} />

  <div class="flex-grow">
    {#if currentRoute === 'home'}
      <Home bind:currentRoute={currentRoute} />
    {:else if currentRoute === 'about'}
      <About />
    {:else if currentRoute === 'contact'}
      <Contact />
    {:else if currentRoute === 'builder'}
      <Builder handoff={builderHandoff} onHandoffConsumed={() => (builderHandoff = null)} />
    {:else if currentRoute === 'library'}
      <Library onOpenInBuilder={openInBuilder} />
    {:else if currentRoute === 'predict' && desktop}
      <Predict />
    {/if}
  </div>
</div>
