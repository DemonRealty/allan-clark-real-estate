/* Property cards sourced from reviewed, locally stored JSON; no third-party iframe. */
(async function(){
  const root=document.querySelector('[data-property-status]');
  if(!root)return;
  const status=root.dataset.propertyStatus;
  try{
    const response=await fetch('data/properties.json',{cache:'no-store'});
    if(!response.ok)throw new Error('Missing property data');
    const payload=await response.json();
    const properties=(payload.properties||[]).filter(p=>p.status===status && p.verified===true && p.url && p.address);
    if(!properties.length)return; // retain existing placeholder content
    const grid=document.createElement('div');grid.className='property-grid';
    for(const p of properties){
      const card=document.createElement('article');card.className='property-card';
      const a=document.createElement('a');a.href=p.url;a.target='_blank';a.rel='noopener noreferrer';
      if(p.image){const img=document.createElement('img');img.src=p.image;img.alt='Property at '+p.address;img.loading='lazy';a.append(img);}
      const info=document.createElement('div');info.className='property-card-body';
      const title=document.createElement('h3');title.textContent=p.address;info.append(title);
      if(p.price){const price=document.createElement('p');price.className='property-price';price.textContent=p.price;info.append(price);}
      const features=[p.bedrooms&&p.bedrooms+' beds',p.bathrooms&&p.bathrooms+' baths',p.parking&&p.parking+' parking'].filter(Boolean);
      if(features.length){const meta=document.createElement('p');meta.textContent=features.join(' · ');info.append(meta);}
      const more=document.createElement('span');more.textContent='View property →';info.append(more);a.append(info);card.append(a);grid.append(card);
    }
    root.replaceChildren(grid);
  }catch(error){console.warn('Property data unavailable; retaining fallback.',error);}
})();