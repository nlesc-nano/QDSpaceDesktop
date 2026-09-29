<script>
  let name = $state('');
  let email = $state('');
  let subject = $state('General Inquiry');
  let message = $state('');
  let status = $state('idle'); // idle | sending | success

  async function handleSubmit(e) {
    e.preventDefault();
    status = 'sending';
    // Simulate API logic
    setTimeout(() => { status = 'success'; }, 1000);
  }
</script>

<div class="min-h-screen bg-slate-50 font-sans selection:bg-brand-100 py-24 px-4">
  <div class="max-w-6xl mx-auto flex flex-col lg:flex-row gap-24 items-start">
    
    <div class="flex-1 lg:sticky lg:top-32">
      <div class="inline-block px-4 py-1.5 rounded-full bg-brand-50 text-brand-700 text-xs font-extrabold uppercase tracking-widest mb-8">Get in Touch</div>
      <h1 class="font-heading text-6xl font-extrabold text-slate-900 mb-8 tracking-tight">Let's <span class="text-brand-600">Connect</span></h1>
      <p class="text-xl text-slate-600 mb-16 leading-relaxed font-medium">
        Whether you are looking to contribute to our Library, reporting a technical issue with the Builder, or discussing research collaborations, we are ready to assist.
      </p>

      <div class="space-y-12">
        <div class="flex gap-6 items-center group">
          <div class="w-16 h-16 bg-white rounded-[1.5rem] shadow-soft flex items-center justify-center text-brand-600 flex-shrink-0 group-hover:scale-110 transition-transform duration-300">
            <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
          </div>
          <div>
            <h4 class="font-bold text-slate-900 text-lg mb-1">Email Us</h4>
            <a href="mailto:ivan.infante@bcmaterials.net" class="text-brand-600 hover:text-brand-700 font-bold text-xl transition-colors">ivan.infante@bcmaterials.net</a>
          </div>
        </div>

        <div class="flex gap-6 items-center group">
          <div class="w-16 h-16 bg-white rounded-[1.5rem] shadow-soft flex items-center justify-center text-brand-600 flex-shrink-0 group-hover:scale-110 transition-transform duration-300">
            <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
          </div>
          <div>
            <h4 class="font-bold text-slate-900 text-lg mb-1">Our Lab</h4>
            <p class="text-slate-600 text-lg leading-relaxed font-medium">
              BCMaterials, UPV/EHU Science Park<br>
              48940 Leioa, Bilbao, Spain
            </p>
          </div>
        </div>
      </div>
    </div>

    <div class="flex-1 w-full">
      <div class="bg-white p-12 md:p-16 rounded-[4rem] shadow-soft border border-slate-100 relative overflow-hidden">
        {#if status === 'success'}
          <div class="text-center py-20 relative z-10">
            <div class="w-24 h-24 bg-emerald-100 text-emerald-600 rounded-[2.5rem] flex items-center justify-center mx-auto mb-8 shadow-sm">
              <svg class="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path></svg>
            </div>
            <h3 class="text-4xl font-bold text-slate-900 mb-4">Message Sent</h3>
            <p class="text-xl text-slate-600 font-medium leading-relaxed">Thank you for reaching out. Our team will get back to you as soon as possible.</p>
            <button class="mt-12 text-brand-600 font-extrabold text-lg hover:underline underline-offset-8" onclick={() => status = 'idle'}>Send another message</button>
          </div>
        {:else}
          <form onsubmit={handleSubmit} class="space-y-10 relative z-10">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-10">
                <div>
                  <label class="block text-xs font-extrabold text-slate-400 uppercase tracking-widest mb-4" for="name">Your Name</label>
                  <input id="name" type="text" bind:value={name} required placeholder="Ivan Infante" class="w-full px-8 py-5 rounded-[2rem] bg-slate-50 border-none focus:ring-2 focus:ring-brand-200 outline-none transition-all font-bold text-slate-900">
                </div>
                <div>
                  <label class="block text-xs font-extrabold text-slate-400 uppercase tracking-widest mb-4" for="email">Email Address</label>
                  <input id="email" type="email" bind:value={email} required placeholder="ivan@lab.net" class="w-full px-8 py-5 rounded-[2rem] bg-slate-50 border-none focus:ring-2 focus:ring-brand-200 outline-none transition-all font-bold text-slate-900">
                </div>
            </div>

            <div>
              <label class="block text-xs font-extrabold text-slate-400 uppercase tracking-widest mb-4" for="subject">Subject</label>
              <select id="subject" bind:value={subject} class="w-full px-8 py-5 rounded-[2rem] bg-slate-50 border-none focus:ring-2 focus:ring-brand-200 outline-none transition-all font-bold text-slate-900 appearance-none">
                <option>General Inquiry</option>
                <option>Library Contribution</option>
                <option>Technical Support</option>
                <option>Research Collaboration</option>
              </select>
            </div>

            <div>
              <label class="block text-xs font-extrabold text-slate-400 uppercase tracking-widest mb-4" for="message">Message</label>
              <textarea id="message" bind:value={message} required rows="6" placeholder="How can we help your research today?" class="w-full px-8 py-5 rounded-[2rem] bg-slate-50 border-none focus:ring-2 focus:ring-brand-200 outline-none transition-all font-bold text-slate-900 resize-none"></textarea>
            </div>

            <button type="submit" disabled={status === 'sending'} class="w-full bg-brand-600 hover:bg-brand-700 text-white font-extrabold py-6 rounded-[2rem] shadow-glow transition-all active:scale-95 text-xl flex items-center justify-center gap-3">
              {status === 'sending' ? 'Processing...' : 'Send Message'}
              {#if status !== 'sending'}
                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
              {/if}
            </button>
          </form>
        {/if}
      </div>
    </div>

  </div>
</div>

