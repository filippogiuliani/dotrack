<script module>
  import { app } from '../lib/store.svelte.js';
  /** value: 'all' | 'mine' (mine + anyone's) | 'anyone' | a member id | 'p<id>' for a person without an account */
  export function matchesWho(item, value) {
    if (value === 'all') return true;
    if (value === 'mine') return !item.person_id && (!item.assignee_id || item.assignee_id === app.me.user.id);
    if (value === 'anyone') return !item.assignee_id && !item.person_id;
    if (String(value).startsWith('p')) return item.person_id === Number(value.slice(1));
    return item.assignee_id === Number(value);
  }
</script>

<script>
  // "Who" filter, shown only when there is someone else in the family (with or without an account)
  import { t } from '../lib/i18n.svelte.js';
  let { value = $bindable('all') } = $props();
  const others = $derived((app.me?.members ?? []).filter((m) => m.id !== app.me.user.id));
  const people = $derived(app.me?.people ?? []);
</script>

{#if others.length || people.length}
  <div class="chips scroll who" role="group" aria-label={t('assign.filter')}>
    <button class="chip" class:on={value === 'all'} onclick={() => (value = 'all')}>{t('assign.all')}</button>
    <button class="chip" class:on={value === 'mine'} onclick={() => (value = 'mine')}>{t('assign.mine')}</button>
    {#each others as m (m.id)}
      <button class="chip" class:on={value === String(m.id)} onclick={() => (value = String(m.id))}>{t('assign.of', { name: m.name })}</button>
    {/each}
    {#each people as p (p.id)}
      <button class="chip" class:on={value === 'p' + p.id} onclick={() => (value = 'p' + p.id)}>{p.name}</button>
    {/each}
    <button class="chip" class:on={value === 'anyone'} onclick={() => (value = 'anyone')}>{t('assign.unassigned')}</button>
  </div>
{/if}

<style>.who { margin-bottom: 4px; }</style>
