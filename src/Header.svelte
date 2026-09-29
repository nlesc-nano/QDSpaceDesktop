<script>
  import { isDesktopApp } from './lib/desktop.js';

  let { currentRoute = $bindable() } = $props();

  const desktop = isDesktopApp();

  const navItems = [
    { id: 'home', label: 'Home' },
    { id: 'library', label: 'Library' },
    { id: 'builder', label: 'Builder' },
    ...(desktop ? [{ id: 'predict', label: 'Predict' }] : []),
    { id: 'contact', label: 'Contact' },
  ];
</script>

<header class="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-slate-200/60 shadow-sm transition-all">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="flex items-center justify-between h-16">
      
      <button class="flex items-center gap-3 transition-transform hover:scale-[1.02]" onclick={() => currentRoute = 'home'}>
        <img src="/assets/logos/QD_Builder_mini.png" alt="QD Space" class="h-8 w-auto drop-shadow-sm" />
        <span class="font-heading font-bold text-xl tracking-tight text-slate-900">
          Quantum Dot <span class="text-brand-600">Space</span>
          {#if desktop}
            <span class="ml-1 text-xs font-semibold uppercase tracking-wider text-brand-500 align-middle">Desktop</span>
          {/if}
        </span>
      </button>

      <nav class="hidden md:flex space-x-1">
        {#each navItems as item}
          <button 
            onclick={() => currentRoute = item.id}
            class="px-4 py-2 rounded-full font-medium text-sm transition-all duration-200 
                   {currentRoute === item.id 
                     ? 'bg-brand-50 text-brand-700 font-semibold' 
                     : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}">
            {item.label}
          </button>
        {/each}
      </nav>
    </div>
  </div>
</header>
