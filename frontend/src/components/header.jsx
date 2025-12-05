import { createEffect, createMemo, createSignal, onMount, For } from "solid-js";
import { api } from "../api";

/**
 *
 * @param {Object} props
 * @param {string} props.sort
 * @param {string} props.search
 * @param {string} props.filteredTag
 * @param {string[]} props.tagOptions
 * @param {Function} props.onSearchChange
 * @param {Function} props.onTagChange
 * @param {Function} props.onNewLanBtnClick
 * @param {Function} props.viewMode
 * @param {Function} props.onViewModeChange
 * @param {boolean} props.selectionMode
 * @param {Function} props.onSelectionModeChange
 */
export function Header(props) {
  const [isScheduling, setIsScheduling] = createSignal(false);
  const [scheduleMessage, setScheduleMessage] = createSignal(null);

  const handleAutoschedule = async () => {
    if (isScheduling()) return;

    setIsScheduling(true);
    setScheduleMessage(null);

    try {
      const response = await fetch(`${api}/autoschedule`, {
        method: 'POST',
        mode: 'cors',
        headers: { 'Content-Type': 'application/json' }
      });

      const result = await response.json();

      if (result.success) {
        setScheduleMessage({ type: 'success', text: 'Tasks scheduled successfully!' });
      } else {
        setScheduleMessage({ type: 'error', text: `Scheduling failed: ${result.error}` });
      }
    } catch (error) {
      setScheduleMessage({ type: 'error', text: 'Network error occurred' });
      console.error('Autoschedule error:', error);
    } finally {
      setIsScheduling(false);
      setTimeout(() => setScheduleMessage(null), 5000);
    }
  };

  const filterSelect = createMemo(() => {
    if (!props.tagOptions.length) {
      return null;
    }
    return (
      <>
        <div class="app-header__group-item-label">Filter by tag:</div>
        <select
          onChange={props.onTagChange}
          value={props.filteredTag || "none"}
        >
          <option value="none">None</option>
          <For each={props.tagOptions}>
            {(tag) => <option value={tag}>{tag}</option>}
          </For>
        </select>
      </>
    );
  });

  return (
    <header class="app-header">
      <input
        placeholder="Search"
        type="text"
        onInput={(e) => props.onSearchChange(e.target.value)}
        class="search-input"
      />
      <div class="app-header__group-item">
        <div class="app-header__group-item-label">Sort by:</div>
        <select onChange={props.onSortChange} value={props.sort}>
          <option value="none">Manually</option>
          <option value="name:asc">Name asc</option>
          <option value="name:desc">Name desc</option>
          <option value="tags:asc">Tags asc</option>
          <option value="tags:desc">Tags desc</option>
          <option value="due:asc">Due date asc</option>
          <option value="due:desc">Due date desc</option>
          <option value="lastUpdated:desc">Last updated</option>
          <option value="createdFirst:asc">Created first</option>
        </select>
      </div>
      <div class="app-header__group-item">
        {filterSelect()}
      </div>
      <div class="app-header__group-item">
        <div class="app-header__group-item-label">View mode:</div>
        <select onChange={props.onViewModeChange} value={props.viewMode}>
          <option value="extended">Extended</option>
          <option value="regular">Regular</option>
          <option value="compact">Compact</option>
          <option value="tight">Tight</option>
        </select>
      </div>
      <button
        type="button"
        onClick={props.onNewLaneBtnClick}
        disabled={props.selectionMode}
      >
        New lane
      </button>
      <button
        type="button"
        onClick={handleAutoschedule}
        disabled={props.selectionMode || isScheduling()}
        title="Schedule tasks to calendar"
      >
        {isScheduling() ? 'Scheduling...' : 'Auto Schedule'}
      </button>
      {scheduleMessage() && (
        <div class={`schedule-notification schedule-notification--${scheduleMessage().type}`}>
          {scheduleMessage().text}
        </div>
      )}
      <button
        type="button"
        onClick={() => props.onSelectionModeChange?.(!props.selectionMode)}
        class={props.selectionMode ? "button--active" : ""}
      >
        {props.selectionMode ? "Exit selection" : "Select cards"}
      </button>
    </header>
  );
}
