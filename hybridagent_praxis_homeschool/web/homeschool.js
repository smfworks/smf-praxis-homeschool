/* Household-first Homeschool Command Deck. No child PII is rendered here. */
(function(){
  'use strict';
  const mount = document.getElementById('homeschool-mount');
  const section = document.getElementById('homeschool-section');
  if(!mount || !section) return;

  const nice = value => String(value || '').replaceAll('_',' ').replace(/\b\w/g, c=>c.toUpperCase());
  const safeHttpUrl = value => {
    try {
      const url = new URL(String(value));
      return ['http:','https:'].includes(url.protocol) ? url.href : '';
    } catch(_) { return ''; }
  };
  const element = (tag, options={}) => {
    const item = document.createElement(tag);
    if(options.id) item.id = options.id;
    if(options.className) item.className = options.className;
    if(options.text !== undefined) item.textContent = String(options.text);
    if(options.value !== undefined) item.value = String(options.value);
    if(options.type) item.type = options.type;
    if(options.maxLength) item.maxLength = options.maxLength;
    if(options.autocomplete) item.autocomplete = options.autocomplete;
    if(options.selected) item.selected = true;
    if(options.target) item.target = options.target;
    if(options.rel) item.rel = options.rel;
    if(options.href) item.href = options.href;
    return item;
  };
  const append = (parent, ...children) => {
    children.flat().filter(Boolean).forEach(child => parent.append(child));
    return parent;
  };
  const label = (text, control) => append(element('label'), document.createTextNode(text), control);
  const option = (value, text, selected=false) => element('option', {value, text, selected});
  const privateNotice = text => element('div', {className:'hs-private', text});
  const warning = text => element('div', {className:'hs-warning', text});

  async function request(url, options){
    const response = await fetch(url, options);
    const body = await response.json().catch(()=>({error:'Invalid server response'}));
    if(!response.ok && !body.error) body.error = 'HTTP '+response.status;
    return body;
  }

  function academicStart(){
    const now = new Date();
    const year = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear()-1;
    return year+'-08-01';
  }

  function render(data){
    if(!data || !data.active){ section.hidden = true; return; }
    section.hidden = false;
    mount.replaceChildren();
    const profile = data.profile || {};
    const calendar = data.calendar || {tasks:[],warnings:[]};

    const head = element('div', {className:'hs-head'});
    append(head,
      element('span', {className:'hs-title', text:(profile.name || '')+' · '+(profile.state || '')}),
      element('span', {className:'hs-badge', text:'Parent operated'}));

    const grid = element('div', {className:'hs-grid'});
    const instruction = element('div', {className:'hs-stat'});
    append(instruction,
      element('b', {text:profile.instruction_days || 'Route'}),
      element('span', {text:profile.instruction_days ? 'required days' : 'route-defined time'}));
    const assessment = element('div', {className:'hs-stat'});
    append(assessment,
      element('b', {text:(profile.assessment_grades || []).join(', ') || '—'}),
      element('span', {text:'assessment grades'}));
    append(grid, instruction, assessment);

    const stateSelect = element('select', {id:'hs-state'});
    (data.states || []).forEach(state => stateSelect.append(option(state, state, state === profile.state)));
    const routeSelect = element('select', {id:'hs-route'});
    routeSelect.append(option('', 'Choose route…'));
    (profile.routes || []).forEach(route => routeSelect.append(
      option(route, nice(route), route === data.route)));
    const commencementSelect = element('select', {id:'hs-commencement'});
    const commencement = calendar.commencement || 'not_yet_started';
    [
      ['not_yet_started','Not yet started'],
      ['initial_start','First year / initial start'],
      ['midyear_start','Starting midyear'],
      ['annual_continuation','Continuing annual program']
    ].forEach(item => commencementSelect.append(option(item[0], item[1], item[0] === commencement)));
    const startInput = element('input', {
      id:'hs-start', type:'date', value:calendar.school_year_start || academicStart()
    });
    const materialsInput = element('input', {
      id:'hs-materials-received', type:'date', value:calendar.materials_received_on || ''
    });
    const reportingInput = element('input', {
      id:'hs-reporting-dates', maxLength:240, autocomplete:'off',
      value:(calendar.reporting_dates || []).join(', ')
    });
    const assessmentInput = element('input', {
      id:'hs-assessment-due', type:'date', value:calendar.assessment_due_date || ''
    });
    const oversightInput = element('input', {
      id:'hs-oversight', maxLength:120, autocomplete:'off'
    });
    const form = element('form', {id:'hs-context', className:'hs-form'});
    append(form,
      label('State', stateSelect),
      label('Parent-confirmed route', routeSelect),
      label('Program status', commencementSelect),
      label('School year starts', startInput),
      label('District materials received (event-driven deadlines)', materialsInput),
      label('Parent-selected reporting dates (comma-separated ISO dates)', reportingInput),
      label('Parent-selected assessment / evaluator date', assessmentInput),
      label('Oversight / umbrella (if applicable)', oversightInput),
      element('button', {type:'submit', text:'Confirm route & build calendar'}));

    const source = element('div', {className:'hs-source'});
    append(source,
      element('b', {text:'Authority:'}),
      document.createTextNode(' '+(profile.source_citation || '')+' · verified '+
        (profile.verified_on || '')+' · '+nice(profile.confidence)),
      element('br'));
    const sourceUrl = safeHttpUrl(profile.source_url);
    if(sourceUrl){
      append(source, element('a', {
        text:'Open source', href:sourceUrl, target:'_blank', rel:'noopener noreferrer'
      }));
    } else {
      append(source, element('span', {text:'Source URL withheld'}));
    }

    const calendarContainer = element('div');
    calendarContainer.append(element('b', {text:'Compliance calendar'}));
    const tasks = (calendar.tasks || []).slice(0,8);
    if(tasks.length){
      tasks.forEach(task => {
        const taskNode = element('div', {className:'hs-task'});
        const detail = element('div');
        append(detail,
          document.createTextNode(String(task.title || '')),
          element('small', {text:task.external_action ? 'Parent action held' : 'Household task'}));
        append(taskNode, element('time', {text:task.due_date || ''}), detail);
        calendarContainer.append(taskNode);
      });
    } else {
      calendarContainer.append(element('div', {className:'hs-empty', text:'No route-confirmed tasks yet.'}));
    }

    const surfaces = element('div', {className:'hs-surfaces'});
    (data.surfaces || []).forEach(name => surfaces.append(
      element('span', {className:'hs-surface', text:name})));

    append(mount,
      head,
      grid,
      form,
      data.route
        ? privateNotice('✓ Route confirmed by parent. Drafts only; filings remain SEND-held.')
        : warning('Choose and confirm the legal route before Praxis labels a requirement applicable.'),
      source,
      (calendar.warnings || []).map(item => warning(item)),
      calendarContainer,
      surfaces,
      privateNotice('Parent-owned · sibling-isolated · no ads/training/profiling · external disclosures held'));
    stateSelect.addEventListener('change', previewState);
    form.addEventListener('submit', confirmRoute);
  }

  async function previewState(event){
    mount.setAttribute('aria-busy','true');
    const data = await request('/api/homeschool/context', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({state:event.target.value})
    });
    mount.removeAttribute('aria-busy');
    render(data);
  }

  async function confirmRoute(event){
    event.preventDefault();
    const reportingDates = document.getElementById('hs-reporting-dates').value
      .split(',').map(value=>value.trim()).filter(Boolean);
    const payload = {
      state:document.getElementById('hs-state').value,
      route:document.getElementById('hs-route').value,
      commencement:document.getElementById('hs-commencement').value,
      school_year_start:document.getElementById('hs-start').value,
      materials_received_on:document.getElementById('hs-materials-received').value,
      reporting_dates:reportingDates,
      assessment_due_date:document.getElementById('hs-assessment-due').value,
      oversight_entity:document.getElementById('hs-oversight').value,
      parent_confirmed:true
    };
    mount.setAttribute('aria-busy','true');
    const data = await request('/api/homeschool/context', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
    });
    mount.removeAttribute('aria-busy');
    if(data.error){
      mount.prepend(element('div', {
        className:'hs-error',
        text:data.error+': '+(data.findings || []).map(item=>item.message).join(' ')
      }));
      return;
    }
    render(data);
  }

  async function load(){
    try {
      render(await request('/api/homeschool'));
    } catch(error) {
      mount.replaceChildren(element('div', {
        className:'hs-error', text:'Could not load Homeschool Command Deck: '+String(error)
      }));
    }
  }

  document.addEventListener('DOMContentLoaded', load);
  window.addEventListener('praxis:refresh', load);
})();
