<script>
  let { currentRoute = $bindable() } = $props();
</script>

<div class="min-h-screen bg-slate-50 font-sans selection:bg-brand-100 pb-24">
  
  <section class="relative pt-24 pb-20 px-4 overflow-hidden text-center">
    <div class="absolute top-[-10%] left-[-10%] w-96 h-96 bg-brand-100 rounded-full mix-blend-multiply filter blur-3xl opacity-50 pointer-events-none"></div>
    <div class="absolute bottom-[-10%] right-[-10%] w-96 h-96 bg-accent-100 rounded-full mix-blend-multiply filter blur-3xl opacity-50 pointer-events-none"></div>

    <div class="relative z-10 max-w-4xl mx-auto">
      <h1 class="font-heading text-6xl md:text-7xl font-extrabold text-slate-900 tracking-tight leading-tight mb-8">
        Accelerating <span class="text-transparent bg-clip-text bg-gradient-to-r from-brand-600 to-accent-500">Quantum Dot</span> Discovery
      </h1>
      <p class="text-xl md:text-2xl text-slate-600 font-medium max-w-2xl mx-auto leading-relaxed">
        An integrated computational ecosystem for building, passivating, and analyzing nanocrystals with unprecedented precision.
      </p>
    </div>
  </section>

  <section class="max-w-6xl mx-auto px-4 mb-40 relative z-10">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-10">
      
      <button 
        class="group relative bg-white rounded-[3rem] p-12 border border-slate-100 shadow-soft hover:shadow-2xl hover:-translate-y-2 transition-all duration-500 text-center overflow-hidden cursor-pointer"
        onclick={() => currentRoute = 'library'}>
        <div class="absolute inset-0 bg-gradient-to-br from-accent-50/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"></div>
        <div class="relative z-10 flex flex-col items-center">
          <img src="/assets/logos/QD_Library_mini.png" alt="Library" class="h-50 mx-auto mb-8 mix-blend-multiply group-hover:scale-110 transition-transform duration-500" />
          <h2 class="font-heading text-3xl font-bold text-slate-900 mb-4 group-hover:text-accent-600 transition-colors">Quantum Dot Library</h2>
          <p class="text-slate-600 font-medium leading-relaxed max-w-xs">Access a plethora of DFT-relaxed quantum dots, including band structures and electronic properties.</p>
        </div>
      </button>

      <button 
        class="group relative bg-white rounded-[3rem] p-12 border border-slate-100 shadow-soft hover:shadow-2xl hover:-translate-y-2 transition-all duration-500 text-center overflow-hidden cursor-pointer"
        onclick={() => currentRoute = 'builder'}>
        <div class="absolute inset-0 bg-gradient-to-br from-brand-50/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"></div>
        <div class="relative z-10 flex flex-col items-center">
          <img src="/assets/logos/QD_Builder_mini.png" alt="Builder" class="h-54 mx-auto mb-8 mix-blend-multiply group-hover:scale-110 transition-transform duration-500" />
          <h2 class="font-heading text-3xl font-bold text-slate-900 mb-4 group-hover:text-brand-600 transition-colors">Quantum Dot Builder</h2>
          <p class="text-slate-600 font-medium leading-relaxed max-w-xs">Create core/shell structures with automated trap-free passivation and global charge neutrality.</p>
        </div>
      </button>

    </div>
  </section>

  <section class="max-w-6xl mx-auto px-4 mb-40">
    
    <div class="flex flex-col lg:flex-row items-center gap-20 mb-32">
        <div class="flex-1 order-2 lg:order-1">
            <h3 class="font-heading text-4xl font-bold text-slate-900 mb-6 tracking-tight">High-Fidelity <span class="text-accent-500">Curated Data</span></h3>
            <p class="text-lg text-slate-600 leading-relaxed mb-8 font-medium">
                Our Library is unique in providing Density Functional Theory (DFT) modeling for a wide plethora of quantum dots with ligands, aligned with experiments across increasing sizes and shapes.
            </p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div class="p-6 rounded-3xl bg-white border border-slate-100 shadow-sm hover:shadow-md transition-shadow">
                    <div class="text-accent-600 font-bold mb-1">DFT-Relaxed</div>
                    <p class="text-sm text-slate-500">Geometries optimized for quantum mechanical accuracy.</p>
                </div>
                <div class="p-6 rounded-3xl bg-white border border-slate-100 shadow-sm hover:shadow-md transition-shadow">
                    <div class="text-accent-600 font-bold mb-1">Dynamic Insights</div>
                    <p class="text-sm text-slate-500">Selected models include Molecular Dynamics (MD) trajectories.</p>
                </div>
            </div>
        </div>
        <div class="flex-1 order-1 lg:order-2 flex justify-center">
            <div class="relative w-72 h-72 bg-accent-50 rounded-[4rem] flex items-center justify-center rotate-3 group">
                <div class="absolute inset-0 bg-accent-100 rounded-[4rem] -rotate-6 group-hover:rotate-0 transition-transform duration-500"></div>
                <img src="/assets/logos/QD_Library_mini.png" alt="Library" class="relative z-10 w-44 h-auto mix-blend-multiply" />
            </div>
        </div>
    </div>

    <div class="flex flex-col lg:flex-row items-center gap-20 mb-40">
        <div class="flex-1 flex justify-center">
            <div class="relative w-72 h-72 bg-brand-50 rounded-[4rem] flex items-center justify-center -rotate-3 group">
                <div class="absolute inset-0 bg-brand-100 rounded-[4rem] rotate-6 group-hover:rotate-0 transition-transform duration-500"></div>
                <img src="/assets/logos/QD_Builder_mini.png" alt="Builder" class="relative z-10 w-44 h-auto mix-blend-multiply" />
            </div>
        </div>
        <div class="flex-1">
            <h3 class="font-heading text-4xl font-bold text-slate-900 mb-6 tracking-tight">Automated <span class="text-brand-600">Surface Engineering</span></h3>
            <p class="text-lg text-slate-600 leading-relaxed mb-8 font-medium">
                We bridge the gap between theory and experiment with a real-time passivation engine that ensures surface ions remain properly coordinated to deliver trap-free models.
            </p>
            <div class="space-y-4">
                <div class="flex items-center gap-5 p-5 bg-white rounded-[2rem] border border-slate-100 shadow-sm">
                    <div class="w-12 h-12 rounded-2xl bg-brand-50 text-brand-600 flex items-center justify-center text-xl">⚡</div>
                    <span class="font-bold text-slate-800">Global Charge Neutrality Balancing</span>
                </div>
                <div class="flex items-center gap-5 p-5 bg-white rounded-[2rem] border border-slate-100 shadow-sm">
                    <div class="w-12 h-12 rounded-2xl bg-brand-50 text-brand-600 flex items-center justify-center text-xl">💎</div>
                    <span class="font-bold text-slate-800">Trap-Free Electronic State Modeling</span>
                </div>
            </div>
        </div>
    </div>
  </section>

  <section class="max-w-6xl mx-auto px-4">
    <div class="bg-white rounded-[4rem] p-10 md:p-16 border border-slate-200 shadow-soft relative overflow-hidden group">
        <div class="absolute top-0 right-0 w-80 h-80 bg-slate-50 rounded-full translate-x-32 -translate-y-32 group-hover:scale-110 transition-transform duration-700"></div>

        <div class="relative z-10">
            <div class="flex flex-col lg:flex-row items-start gap-16">
                <div class="flex-1">
                    <div class="inline-block px-4 py-1.5 rounded-full bg-brand-50 text-brand-700 text-xs font-extrabold uppercase tracking-widest mb-8">Research Leadership</div>
                    <h2 class="font-heading text-5xl font-extrabold text-slate-900 mb-8 tracking-tight">The Infante Group</h2>
                    
                    <p class="text-xl text-slate-600 leading-relaxed mb-10">
                        Led by <strong>Ivan Infante</strong>, Ikerbasque Research Professor at <strong>BCMaterials</strong>, our group operates at the intersection of chemistry, physics, and materials science.
                        We specialize in the atomistic modeling of colloidal semiconductor nanocrystals, providing the theoretical foundation for next-generation optoelectronic devices.
                    </p>

                    <div class="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
                        <div class="space-y-3">
                            <h4 class="font-heading font-bold text-slate-900 flex items-center gap-2">
                                <span class="text-brand-600">●</span> Surface & Interface Science
                            </h4>
                            <p class="text-sm text-slate-500 leading-relaxed">
                                Investigating the complex interaction between organic ligands and inorganic cores to eliminate electronic trap states and achieve high photoluminescence quantum yields.
                            </p>
                        </div>
                        <div class="space-y-3">
                            <h4 class="font-heading font-bold text-slate-900 flex items-center gap-2">
                                <span class="text-brand-600">●</span> Excited State Dynamics
                            </h4>
                            <p class="text-sm text-slate-500 leading-relaxed">
                                Using advanced DFT and Molecular Dynamics to predict charge transport, energy transfer, and stability in quantum dots and perovskites.
                            </p>
                        </div>
                        <div class="space-y-3">
                            <h4 class="font-heading font-bold text-slate-900 flex items-center gap-2">
                                <span class="text-brand-600">●</span> Material Discovery
                            </h4>
                            <p class="text-sm text-slate-500 leading-relaxed">
                                Designing "trap-free" materials for high-performance radiation detectors, solar cells, and environmentally friendly light-emitting diodes.
                            </p>
                        </div>
                        <div class="space-y-3">
                            <h4 class="font-heading font-bold text-slate-900 flex items-center gap-2">
                                <span class="text-brand-600">●</span> Computational Tooling
                            </h4>
                            <p class="text-sm text-slate-500 leading-relaxed">
                                Developing open-access software stacks that bridge the gap between fundamental atomistic simulations and experimental device fabrication.
                            </p>
                        </div>
                    </div>
                </div>

                <div class="w-full lg:w-80 flex-shrink-0">
                    <div class="space-y-4">
                        <div class="bg-slate-50 p-8 rounded-[2.5rem] border border-slate-100">
                            <h4 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Affiliation</h4>
                            <div class="flex items-center gap-4">
                                <div class="w-12 h-12 bg-white rounded-2xl flex items-center justify-center shadow-sm text-xl font-bold text-slate-800 font-heading">B</div>
                                <div>
                                    <p class="font-bold text-slate-900 leading-tight">BCMaterials</p>
                                    <p class="text-sm text-slate-500 font-medium leading-tight">Basque Center for Materials</p>
                                </div>
                            </div>
                        </div>

                        <a href="https://scholar.google.com/citations?user=fw_Uyi4AAAAJ&hl=en" target="_blank" 
                           class="block bg-brand-600 hover:bg-brand-700 p-8 rounded-[2.5rem] text-white transition-all shadow-glow hover:shadow-xl group/btn">
                            <div class="flex justify-between items-center mb-2">
                                <span class="text-xs font-bold uppercase tracking-widest text-brand-200">100+ Publications</span>
                                <svg class="w-6 h-6 text-brand-200 group-hover/btn:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
                            </div>
                            <h4 class="font-heading font-bold text-xl">Google Scholar</h4>
                            <p class="text-xs text-brand-200/80 mt-1 font-medium italic">Quantum Dots · DFT · Surface Science</p>
                        </a>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="mt-32 pt-16 border-t border-slate-200 text-center">
        <p class="font-heading font-bold text-slate-400 uppercase tracking-widest text-xs mb-12">Institutional Support</p>
        
        <div class="flex flex-wrap justify-center items-center gap-8 md:gap-10">
            
            <div class="bg-white rounded-[2rem] shadow-sm border border-slate-100 p-6 h-32 min-w-[16rem] flex items-center justify-center opacity-80 grayscale hover:grayscale-0 hover:opacity-100 hover:-translate-y-1 hover:shadow-md transition-all duration-300">
                <img src="/assets/logos/eu_funded_en.jpg" alt="Funded by the EU" class="max-h-full max-w-full object-contain" />
            </div>

            <div class="bg-white rounded-[2rem] shadow-sm border border-slate-100 p-6 h-32 min-w-[16rem] flex items-center justify-center opacity-80 grayscale hover:grayscale-0 hover:opacity-100 hover:-translate-y-1 hover:shadow-md transition-all duration-300">
                <img src="/assets/logos/Ikerbasque_Logoa.jpg" alt="Ikerbasque" class="max-h-full max-w-full object-contain" />
            </div>

            <div class="bg-white rounded-[2rem] shadow-sm border border-slate-100 p-6 h-32 min-w-[16rem] flex items-center justify-center opacity-80 grayscale hover:grayscale-0 hover:opacity-100 hover:-translate-y-1 hover:shadow-md transition-all duration-300">
                <img src="/assets/logos/Logotipo_del_Gobierno_Vasco.svg.png" alt="Gobierno Vasco" class="max-h-full max-w-full object-contain" />
            </div>

            <div class="bg-white rounded-[2rem] shadow-sm border border-slate-100 p-6 h-32 min-w-[16rem] flex items-center justify-center opacity-80 grayscale hover:grayscale-0 hover:opacity-100 hover:-translate-y-1 hover:shadow-md transition-all duration-300">
                <img src="/assets/logos/TTT_logo.png" alt="TTT" class="max-h-full max-w-full object-contain" />
            </div>

            <div class="bg-white rounded-[2rem] shadow-sm border border-slate-100 p-6 h-32 min-w-[16rem] flex items-center justify-center opacity-80 grayscale hover:grayscale-0 hover:opacity-100 hover:-translate-y-1 hover:shadow-md transition-all duration-300">
                <img src="/assets/logos/ikur_logo.png" alt="IKUR" class="max-h-full max-w-full object-contain" />
            </div>

            <div class="bg-white rounded-[2rem] shadow-sm border border-slate-100 p-6 h-32 min-w-[16rem] flex items-center justify-center opacity-80 grayscale hover:grayscale-0 hover:opacity-100 hover:-translate-y-1 hover:shadow-md transition-all duration-300">
                <img src="/assets/logos/Unicorn_logo.png" alt="Unicorn" class="max-h-full max-w-full object-contain" />
            </div>
            
        </div>
    </div>

  </section>
</div>

