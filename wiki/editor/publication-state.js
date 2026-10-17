export function createPublicationState(button) {
  let generation = 0;
  return {
    reset() { generation++; button.textContent = 'Опубликовать'; },
    pending() {
      const token = ++generation;
      button.textContent = 'Сохранено · публикация…';
      return published => {
        if (token === generation) button.textContent = published ? 'Опубликовано' : 'Сохранено · ошибка публикации';
      };
    }
  };
}
