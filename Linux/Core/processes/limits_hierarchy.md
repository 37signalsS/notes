# Limits Hierarchy

## Определения

**Иерархия лимитов** — порядок применения ограничений ресурсов в Linux. Лимиты применяются от наиболее строгих (cgroups) к наименее строгим (ulimit текущей сессии).

## Основные концепции

### Порядок применения (от высшего к низшему)

1. **cgroups v2** — самые строгие лимиты для контейнеров (`memory.max`, `pids.max`, `cpu.max`)
2. **systemd директивы** — для сервисов (`LimitNOFILE`, `LimitNPROC`, `LimitCORE`)
3. **PAM / limits.conf** — для пользовательских сессий, аутентифицирующихся через PAM
4. **ulimit** — временные лимиты текущей сессии shell

### Ключевые правила

- **cgroups v2 имеют приоритет** над всеми остальными механизмами. Если `memory.max` в cgroup установлен ниже, чем лимит в systemd, процесс будет ограничен cgroup.
- **systemd** — основной и наиболее надежный механизм для сервисов. Директивы `Limit...` в юнит-файле имеют приоритет над глобальными настройками `/etc/systemd/system.conf`.
- **limits.conf** применяется только к сессиям через PAM (SSH, GUI), но **не влияет** на системные сервисы `systemd`.
- **ulimit** действует только для текущей сессии и дочерних процессов.

## Практические сценарии

### Проверка применения лимитов к сервису

```bash
# Проверить настройки systemd
systemctl show my-app.service | grep LimitNOFILE

# Проверить фактические лимиты процесса
cat /proc/$(pgrep -f my-app)/limits | grep "Max open files"

# Проверить cgroup лимиты (v2)
cat /sys/fs/cgroup/system.slice/my-app.service/memory.max
```

### Диагностика конфликта лимитов

Если процесс ограничен сильнее, чем ожидается:

1. Проверьте cgroup: `cat /sys/fs/cgroup/.../memory.max`
2. Проверьте systemd: `systemctl show <service> | grep Limit`
3. Проверьте PAM: `grep <user> /etc/security/limits.conf`
4. Проверьте сессию: `ulimit -a`

---

Полное описание лимитов, типов, механизмов настройки и практических сценариев см. в [**Resource Limits Concepts**](./resource_limits_concepts.md).
