# RBD: Расширенные темы

## Определения и базовые концепции

### Оптимизация производительности

**Параметры монтирования** влияют на производительность RBD-устройств:

| Опция | Описание |
|-------|----------|
| `noatime` | Не обновлять время доступа к файлам |
| `nodiratime` | Не обновлять время доступа к директориям |
| `discard` | Включить TRIM для тонкого выделения (thin provisioning) |

```bash
mount -o noatime,nodiratime,discard /dev/rbd0 /mnt/rbd
```

### Бэкап и восстановление

**Типы бэкапов RBD:**

| Тип | Команда | Примечание |
|-----|---------|------------|
| Полный экспорт | `rbd export` | Создаёт полный образ |
| Инкрементальный | `rbd export-diff` | Требует `object-map` и `fast-diff` |

---

## Практические сценарии

### Бенчмаркинг RBD-устройств

Используйте `fio` для тестирования производительности:

```bash
# Тест последовательной записи
fio --name=write --ioengine=libaio --rw=write --bs=4k \
  --direct=1 --numjobs=1 --size=1G --runtime=60 \
  --filename=/dev/rbd0

# Тест последовательного чтения
fio --name=read --ioengine=libaio --rw=read --bs=4k \
  --direct=1 --numjobs=1 --size=1G --runtime=60 \
  --filename=/dev/rbd0
```

**Параметры `fio`:**
- `--ioengine=libaio` — асинхронный ввод-вывод
- `--direct=1` — прямой доступ (без кэша страницы)
- `--numjobs=1` — одно задание (увеличьте для параллельного теста)

### Операции бэкапа

```bash
# Полный экспорт образа
rbd export kube/my-image /backup/my-image.img

# Импорт образа
rbd import /backup/my-image.img kube/my-image-restored

# Инкрементальный бэкап (по снимку)
rbd export-diff kube/my-image@snap1 /backup/diff.snap1
```

> **Требование**: для инкрементальных бэкапов образ должен иметь включённые `object-map` и `fast-diff`. См. [Определения и концепции](./definitions_and_concepts.md).

---

## Дополнительная информация

- [Официальная документация RBD](https://docs.ceph.com/en/latest/rbd/)
- [Обзор Ceph](../ceph_overview.md)
- [Определения и концепции](./definitions_and_concepts.md) — базовая информация, требования к образам
- [Практические сценарии](./practical_scenarios.md) — установка, управление, монтирование
