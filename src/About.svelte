<script>
  let { currentRoute = $bindable() } = $props();
</script>

<div class="min-h-screen bg-slate-50 py-20 px-4 font-sans">
  <div class="max-w-5xl mx-auto">
    
    <div class="mb-24 text-center">
      <h1 class="font-heading text-5xl md:text-6xl font-extrabold text-slate-900 tracking-tight mb-8">
        Precision <span class="text-brand-600">In-Silico</span> Modeling
      </h1>
      <p class="text-xl text-slate-600 leading-relaxed max-w-3xl mx-auto font-medium">
        Quantum Dot Space is an integrated ecosystem designed to bridge the gap between theoretical modeling and experimental reality.
      </p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-12 mb-24">
      <div class="bg-white p-12 rounded-[2.5rem] shadow-soft hover:shadow-xl transition-shadow border border-slate-50">
        <div class="w-14 h-14 bg-accent-50 text-accent-600 rounded-2xl flex items-center justify-center mb-10">
          <svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79-8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"></path></svg>
        </div>
        <h3 class="font-heading text-3xl font-bold text-slate-900 mb-6">Curated Repository</h3>
        <p class="text-slate-600 leading-relaxed mb-8">
          A high-fidelity database of semiconductor structures. Unlike generic repositories, our data is refined through rigorous computational validation.
        </p>
        <div class="space-y-4">
            <div class="flex items-center gap-4 text-slate-700 font-semibold">
                <div class="w-2 h-2 rounded-full bg-accent-500"></div> Optimized Geometries (DFT)
            </div>
            <div class="flex items-center gap-4 text-slate-700 font-semibold">
                <div class="w-2 h-2 rounded-full bg-accent-500"></div> Dynamic Insights (MD)
            </div>
            <div class="flex items-center gap-4 text-slate-700 font-semibold">
                <div class="w-2 h-2 rounded-full bg-accent-500"></div> Electronic Band Structures
            </div>
        </div>
      </div>

      <div class="bg-white p-12 rounded-[2.5rem] shadow-soft hover:shadow-xl transition-shadow border border-slate-50">
        <div class="w-14 h-14 bg-brand-50 text-brand-600 rounded-2xl flex items-center justify-center mb-10">
          <svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"></path></svg>
        </div>
        <h3 class="font-heading text-3xl font-bold text-slate-900 mb-6">Surface Engineering</h3>
        <p class="text-slate-600 leading-relaxed mb-8">
          Automated passivation logic to solve the "surface trap" problem. We ensure global charge neutrality and proper coordination for experimentally relevant models.
        </p>
        <div class="space-y-4">
            <div class="flex items-center gap-4 text-slate-700 font-semibold">
                <div class="w-2 h-2 rounded-full bg-brand-500"></div> Trap-Free Architectures
            </div>
            <div class="flex items-center gap-4 text-slate-700 font-semibold">
                <div class="w-2 h-2 rounded-full bg-brand-500"></div> Stoichiometric Balancing
            </div>
            <div class="flex items-center gap-4 text-slate-700 font-semibold">
                <div class="w-2 h-2 rounded-full bg-brand-500"></div> Core/Shell Scalability
            </div>
        </div>
      </div>
    </div>

    <div class="bg-white p-12 md:p-16 rounded-[3rem] shadow-soft border border-slate-50 mb-24">
      <div class="flex flex-col lg:flex-row gap-16 items-center">
        <div class="flex-1 text-center lg:text-left">
          <h2 class="font-heading text-4xl font-extrabold text-slate-900 mb-6">The Infante Group</h2>
          <p class="text-lg text-slate-600 leading-relaxed mb-6">
            Led by <strong>Ivan Infante</strong>, Ikerbasque Research Professor at <strong>BCMaterials</strong>, our group develops specialized computational tools to advance the science of colloidal semiconductor nanocrystals.
          </p>
          <p class="text-lg text-slate-600 leading-relaxed">
            Our mission is to provide the scientific community with high-fidelity models for the next generation of radiation detectors and optoelectronic devices.
          </p>
        </div>
        <div class="w-full lg:w-72 flex flex-col gap-4">
          <div class="p-6 bg-slate-50 rounded-[2rem] border border-slate-100">
            <span class="text-xs font-bold text-slate-400 uppercase tracking-widest block mb-1">Affiliation</span>
            <span class="text-base font-bold text-slate-800">BCMaterials, Bilbao</span>
          </div>
          <a href="https://scholar.google.com/citations?user=fw_Uyi4AAAAJ&hl=en" target="_blank" class="p-6 bg-brand-50 rounded-[2rem] border border-brand-100 hover:bg-brand-100 transition-all flex justify-between items-center group">
            <div>
              <span class="text-xs font-bold text-brand-600 uppercase tracking-widest block mb-1">Research Profile</span>
              <span class="text-base font-bold text-brand-700 font-heading">Google Scholar</span>
            </div>
            <svg class="w-5 h-5 text-brand-600 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
          </a>
        </div>
      </div>
    </div>

    <div class="pt-12 border-t border-slate-200">
      <p class="font-heading font-semibold text-slate-400 uppercase tracking-widest text-xs mb-12 text-center">Supported By</p>
      <div class="flex flex-wrap justify-center gap-16 opacity-40 grayscale hover:grayscale-0 transition-all duration-700">
        <div class="h-12 w-40 bg-slate-300 rounded-2xl animate-pulse"></div>
        <div class="h-12 w-40 bg-slate-300 rounded-2xl animate-pulse"></div>
        <div class="h-12 w-40 bg-slate-300 rounded-2xl animate-pulse"></div>
      </div>
    </div>
  </div>
</div>

