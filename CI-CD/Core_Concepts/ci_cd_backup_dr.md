# Резервное копирование и DR для CI/CD

## Определения

- **Backup (Бэкап)** — создание копии данных, артефактов и конфигураций для восстановления при потере, повреждении или компрометации.
- **Restore (Восстановление)** — процесс возврата системы из резервной копии в работоспособное состояние.
- **RPO (Recovery Point Objective)** — максимально допустимая потеря данных, выраженная во времени. Если RPO = 15 минут, то при сбое данные за последние 15 минут могут быть безвозвратно потеряны. Диктует выбор метода бэкапа и репликации.
- **RTO (Recovery Time Objective)** — максимально допустимое время простоя сервиса с момента объявления аварии до возврата в рабочее состояние. Зависит от готовности резервной инфраструктуры и автоматизации восстановления.
- **DR (Disaster Recovery, Аварийное восстановление)** — комплекс процессов и runbook для восстановления CI/CD-инфраструктуры после катастрофических сбоев: потеря площадки, ransomware, коррупция реестра или полное удаление конфигураций.
- **Immutable Backup (Неизменяемый бэкап)** — копия, защищённая от изменения и удаления на уровне хранилища (WORM, append-only policy, объектные блокировки). Цель — предотвратить «тихую» модификацию бэкапа компрометированным узлом.
- **Offsite-копия** — резервная копия, хранящаяся вне основного контура (физически изолированный носитель, выделенный узел в другой сети).
- **Air-gapped Bundle (Автономный бандл)** — самодостаточный архив, содержащий образы, артефакты и конфигурации, достаточные для восстановления CI/CD «с нуля» без внешних запросов.
- **DR Drill (Тренировка восстановления)** — плановое упражнение по восстановлению из бэкапа в изолированной среде (QA/DR-площадка), минимизирующее риск «битых» копий.

## Основные концепции

### Что бэкапить в инфраструктуре CI/CD

Инфраструктура CI/CD сама по себе не несёт продукт, но её простой блокирует выпуски. Поэтому резервное копирование охватывает:

1.  **Реестр образов (Container Registry)** — Harbor, Nexus, Artifactory. Бэкап включает слои образов и метаданные (теги, подписи, отчёты сканирования). Без реестра пайплайн не может собрать артефакт для деплоя.
2.  **Артефакты сборки** — бинарные файлы, пакеты, Helm-чарты, SBOM. Это зеркало зависимостей, без которого сборка в air-gapped или после катастрофы невозможна.
3.  **Конфигурация CI как код** — `.gitlab-ci.yml`, `Jenkinsfile`, `pipeline.yaml`, переменные окружений и сценарии. Должны храниться в Git, но критичные секции (например, защищённые переменные) дублируются в зашифрованном виде.
4.  **Состояние раннеров** — их конфигурации, системные юниты, ключи доступа к реестру. Не сами эфемерные раннеры, а их описание и идентификаторы.
5.  **Секреты и ключи** — экспорты УЦ, токены, пароли. Восстанавливаются через Vault или из зашифрованных архивов с оффлайн-ключом.
6.  **Метаданные пайплайнов и деплоев** — история запусков, статусы, аудит-логи. Нужны для RCA и соответствия Compliance.
7.  **База данных CI-инстанса** — состояние пайплайнов, пользователи, настройки групп. Для GitLab — часть `gitlab-backup`; для Jenkins — каталог `$JENKINS_HOME`.
8.  **Конфигурации прокси, бастиона и внутренних зеркал** — без них раннеры и реестр не имеют доступа к зависимостям.

### RPO/RTO для CI/CD

RTO и RPO для CI/CD определяются не SLA продукта, а допустимым простоем инфраструктуры поставки:

| Компонент | RPO | RTO | Обоснование |
| :--- | :--- | :--- | :--- |
| **Раннеры** | Минуты (immutable-образ) | Минуты | Поднимаются из golden image с параметризацией. |
| **Реестр образов** | Часы (реплика/зеркало) | Часы | Импорт dir-бандла через skopeo + поднятие чистого узла. |
| **Артефакты (Nexus/Artifactory)** | Часы | Часы | rsync с чек-суммой и восстановлением из архива. |
| **CI-конфиг** | Минуты (в Git) | Минуты | `git clone` + импорт секретов из Vault. |
| **База данных CI** | Часы | Часы | Периодический `pg_dump` / встроенный бэкап инстанса. |
| **Секреты** | Минуты | Минуты | Восстановление из Vault snapshot или оффлайн-ключа. |

### Стратегия 3-2-1 для CI/CD

Классическая стратегия хранения бэкапов адаптируется под инфраструктуру CI/CD:

1.  **3 копии:** рабочая версия + локальный бэкап + offsite/air-gapped копия.
2.  **2 носителя:** быстрый диск для оперативного восстановления + медленный/архивный (LTO, NAS, выделенный узел) для долгого хранения.
3.  **1 копия вне контура:** sneakernet-бандл или реплика на выделенный узел в другой подсети, недоступной из основного контура.

### Иммутабельность и проверка

Бэкап считается валидным только при соблюдении трёх условий:

1.  **Целостность:** контрольная сумма (`sha256`) + цифровая подпись (GPG, cosign).
2.  **Неизменяемость:** append-only/WORM на уровне хранилища или физическая изоляция носителя.
3.  **Восстанавливаемость:** регулярный DR drill — восстановление в QA/изолированной среде с проверкой ключевых сценариев (build → push → deploy canary).

### Роли и ответственность

| Фаза | DevOps | SRE | Sysadmin |
| :--- | :--- | :--- | :--- |
| **Планирование** | Определение RPO/RTO для реестра и артефактов; выбор инструментов. | Утверждение SLO на время восстановления CI-инфраструктуры. | Оценка объёма хранилища, планирование дисков/инодов. |
| **Реализация** | Настройка пайплайнов бэкапа; интеграция scan/sign в CI. | Внедрение автоматических проверок (job verify-backup); настройка алертов на провал бэкапа. | Подготовка storage: WORM, ротация, мониторинг места и инодов. |
| **Тестирование** | DR drill через пайплайн (восстановление в QA). | Калибровка RTO, анализ MTTR восстановления. | Восстановление на «голом железе», проверка инициализации раннеров. |
| **Эксплуатация** | Мониторинг статусов бэкапов; обновление runbook. | On-call при инцидентах, координация восстановления. | Ротация носителей, offsite-перемещение бандлов. |

## Практические сценарии

### Сценарий 1: Бэкап реестра Docker/Harbor

Экспорт образов и метаданных реестра для offsite-хранения.

```bash
# 1. Синхронизация реестра в локальную директорию (offline-бандл)
skopeo sync --src docker --dest dir registry.internal/library /backup/registry-$(date +%F)
# → INFO[0000] Syncing registry.internal/library/nginx:1.25 to dir:/backup/registry-2026-06-01

# 2. Экспорт метаданных Harbor (если используется внешняя БД)
pg_dump -h harbor-db.internal -U harbor -d harbor_production -F c -b -v -f /backup/harbor-metadata-$(date +%F).dump
# → pg_dump: last built-in OID=10000
# → pg_dump: dumping extensions
# → pg_dump: dumping database "harbor_production" ...

# 3. Контрольная сумма и подпись бандла
tar -czf /backup/registry-bundle-$(date +%F).tar.gz -C /backup registry-$(date +%F) harbor-metadata-$(date +%F).dump
sha256sum /backup/registry-bundle-$(date +%F).tar.gz > /backup/registry-bundle-$(date +%F).sha256
gpg --detach-sign --armor /backup/registry-bundle-$(date +%F).sha256
# → gpg: signing failed: No secret key (если ключ недоступен — использовать оффлайн-ключ)
```

**Восстановление:**

```bash
# 1. Распаковка и проверка подписи
tar -xzf /backup/registry-bundle-2026-06-01.tar.gz -C /backup/restore/
gpg --verify /backup/restore/registry-bundle-2026-06-01.tar.gz.sha256.asc /backup/restore/registry-bundle-2026-06-01.tar.gz
# → gpg: Good signature from "ci-backup@internal"

# 2. Импорт образов в новый узел реестра
skopeo sync --src dir --dest docker /backup/restore/registry-2026-06-01 registry.internal/library

# 3. Восстановление метаданных Harbor (если нужно)
pg_restore -h harbor-db.internal -U harbor -d harbor_production -v /backup/restore/harbor-metadata-2026-06-01.dump
```

### Сценарий 2: Бэкап артефактов (Nexus/Artifactory)

```bash
# 1. Синхронизация хранилища артефактов
rsync -a --delete --checksum --compress-choice=zstd \
  nexus.internal:/var/lib/nexus/storage /backup/nexus/
# → sending incremental file list
# → ./com/example/app/1.0.0/app-1.0.0.jar

# 2. Генерация манифеста с контрольными суммами
find /backup/nexus -type f -exec sha256sum {} + > /backup/nexus.manifest.sha256

# 3. Подпись манифеста
gpg --detach-sign --armor /backup/nexus.manifest.sha256
# → gpg: signing completed

# 4. Проверка подписи (перед восстановлением)
gpg --verify /backup/nexus.manifest.sha256.asc /backup/nexus.manifest.sha256
# → gpg: Good signature
```

### Сценарий 3: Бэкап конфигурации CI как кода

```bash
# 1. Git bundle всего репозитория с CI-конфигурациями
cd /srv/git/ci-configs && git bundle create /backup/ci-configs-$(date +%F).bundle --all
# → Counting objects: 142, done.
# → Delta compression using up to 8 threads
# → Writing objects: 100% (142/142), 1.2 MiB | 2.3 MiB/s, done.

# 2. Шифрование бандла для air-gapped хранения
gpg --symmetric --cipher-algo AES256 /backup/ci-configs-$(date +%F).bundle
# → Enter passphrase: ********

# 3. Проверка bundle
git clone /backup/ci-configs-2026-06-01.bundle /tmp/ci-restore-test
# → Cloning into '/tmp/ci-restore-test'...
# → done.
rm -rf /tmp/ci-restore-test
```

### Сценарий 4: Автоматический бэкап GitLab (self-hosted)

```bash
# 1. Создание бэкапа (включает БД, репозитории, артефакты, секреты)
docker exec gitlab gitlab-backup create CRON=1
# → [2026-06-01 02:00:01] Creating backup archive: 1748774401_2026_06_01_14.0.0_gitlab_backup.tar

# 2. Бэкап конфигурации и секретов
cp /srv/gitlab/config/gitlab.rb /backup/gitlab-config-$(date +%F).rb
cp /srv/gitlab/config/gitlab-secrets.json /backup/gitlab-secrets-$(date +%F).json

# 3. Offsite-копирование (rsync на выделенный узел)
rsync -avz --progress /backup/gitlab-* backup.internal:/data/offsite/gitlab/

# 4. Проверка бэкапа (размер и контрольная сумма)
ls -lh /srv/gitlab/backups/1748774401_2026_06_01_14.0.0_gitlab_backup.tar
sha256sum /backup/gitlab-config-2026-06-01.rb /backup/gitlab-secrets-2026-06-01.json
```

**Восстановление GitLab:**

```bash
# 1. Остановка сервисов
docker exec gitlab gitlab-ctl stop puma
docker exec gitlab gitlab-ctl stop sidekiq
docker exec gitlab gitlab-ctl stop unicorn

# 2. Восстановление бэкапа
docker exec gitlab gitlab-backup restore BACKUP=1748774401_2026_06_01_14.0.0

# 3. Восстановление конфигурации
cp /backup/gitlab-secrets-2026-06-01.json /srv/gitlab/config/gitlab-secrets.json
cp /backup/gitlab-config-2026-06-01.rb /srv/gitlab/config/gitlab.rb

# 4. Перезапуск
docker exec gitlab gitlab-ctl start
docker exec gitlab gitlab-ctl reconfigure
```

### Сценарий 5: Runbook восстановления после потери реестра

```text
## Runbook: Восстановление Harbor/Nexus после потери узла

### Предварительные требования
- Доступ к offsite-бандлу (физически изолированный носитель или выделенный узел).
- Оффлайн-ключ для GPG/cosign.
- Чистый узел с таким же/большим объёмом диска и версией ОС.

### Шаги
1. Поднять чистый узел реестра из golden image.
2. Восстановить том из снапшота или импортировать dir-бандл через skopeo.
3. Проверить подписи: cosign verify / gpg --verify.
4. Импортировать метаданные БД реестра (если используется отдельная БД).
5. Поднять раннеры (systemd unit из бэкап-конфигов).
6. Прогнать smoke-пайплайн: build → push → deploy canary.
7. Проверить health и доступность артефактов вProduction-среде.
```

### Сценарий 6: DR Drill — тестирование восстановления в QA

```bash
# 1. Создание QA-клона из бэкапа
tar -xzf /backup/registry-bundle-2026-06-01.tar.gz -C /srv/qa-restore/
skopeo sync --src dir --dest docker /srv/qa-restore/registry-2026-06-01 qa-registry.internal/library

# 2. Прогон smoke-пайплайна против QA-реестра
CI_REGISTRY=qa-registry.internal ./run-smoke-pipeline.sh
# → pipeline #1290 started
# → build: OK
# → test: OK
# → canary deploy: OK

# 3. Валидация
curl -sf http://qa-app.internal/healthz
# → OK
echo "DR drill passed: $(date)"
```

## Операции и команды

### Управление бэкапами реестра

```bash
# Экспорт образа в OCI-архив (альтернатива skopeo)
 crane export registry.internal/library/app:1.42.0 - | gzip > app-1.42.0.tar.gz

# Импорт образа из архива
 crane import - < app-1.42.0.tar.gz

# Проверка подписи образа
cosign verify --key cosign.pub registry.internal/library/app:1.42.0
# → Verification: OK
```

### Верификация и подпись

```bash
# Подпись манифеста бэкапа
gpg --detach-sign --armor /backup/nexus.manifest.sha256

# Проверка подписи
gpg --verify /backup/nexus.manifest.sha256.asc /backup/nexus.manifest.sha256
# → gpg: Good signature from "ci-backup@internal"

# Хеш-сумма для проверки целостности
sha256sum /backup/registry-bundle-2026-06-01.tar.gz
# → a1b2c3d4... registry-bundle-2026-06-01.tar.gz
```

### Ротация и очистка

```bash
# Оставить 7 последних бэкапов Nexus
ls -t /backup/nexus-*.tar.gz | tail -n +8 | xargs rm -f

# Очистка старых бэкапов GitLab (старше 30 дней)
find /srv/gitlab/backups -name "*.tar" -mtime +30 -delete

# Проверка свободного места и инодов
df -h /backup
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sdb1       2T   1.2T  800G  60% /backup
df -i /backup
# → Filesystem      Inodes  IUsed  IFree IUse% Mounted on
# → /dev/sdb1      1.3M    800K    500K  62% /
```

### Автоматизация через systemd/cron

```ini
# /etc/systemd/system/ci-backup.service
[Unit]
Description=CI/CD Backup
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ci-backup.sh
```

```ini
# /etc/systemd/system/ci-backup.timer
[Unit]
Description=Daily CI backup at 02:00

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Активация таймера
systemctl daemon-reload
systemctl enable --now ci-backup.timer
# → Created symlink /etc/systemd/system/timers.target.wants/ci-backup.timer
```

## Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Бэкап не восстанавливается | Бэкап никогда не тестировался | Регулярный DR drill в QA; runbook с валидацией. |
| «Бэкап есть, но образы без тегов» | Создан бэкап реестра без метаданных БД | Бэкапить реестр + метаданные БД; см. Сценарий 1. |
| Секреты утекли из бэкапа | Секреты хранятся в открытом виде | Шифрование бэкапов; оффлайн-ключ GPG/cosign; Vault для секретов. |
| Бэкап гибнет вместе с контуром | Нет offsite-копии | Стратегия 3-2-1; sneakernet-бандл или реплика на выделенный узел. |
| Полный диск / исчерпание инодов | Реестр/бэкап переполняют том | Отдельный том, `noatime`, мониторинг `df -h`/`df -i`, GC реестра. |
| Бэкап занимает слишком много места | Нет дедупликации и ротации | Включить ZFS/Btrfs dedup или Borg/Restic; политика ротации. |
| DR занимает часы вместо минут | Отсутствие golden image для раннеров | Подготовить golden image реестра/раннеров; автоматический подъём через systemd/Ansible. |
| Восстановление проходит, но пайплайн падает | Не восстановлены переменные окружения / секреты | Включить в runbook шаг импорта секретов из Vault или зашифрованного архива. |

## Лучшие практики

- **Стратегия 3-2-1:** минимум 3 копии, 2 носителя, 1 offsite/air-gapped.
- **Тестируйте restore:** DR drill минимум раз в квартал; автоматизируйте smoke-пайплайн после восстановления.
- **Иммутабельность:** WORM/append-only на уровне storage; подпись бэкапов GPG/cosign.
- **Шифруйте offsite:** AES-256 для air-gapped бандлов; храните оффлайн-ключ отдельно от носителя.
- **Ротация:** храните не более N последних копий (обычно 7–30); удаляйте старые через `find -mtime +N -delete`.
- **Автоматизация:** cron/systemd-таймер для регулярных бэкапов; алерты на провал job-ы в пайплайне.
- **Документируйте runbook:** пошаговый план восстановления с ответственными, проверенными на drill.
- **Не храните секреты в открытом виде:** Vault с оффлайн-ключом восстановления; секреты не попадают в бэкап CI-инстанса в plaintext.
- **Мониторинг места и инодов:** отдельный том для реестра/бэкапов; алерты на `df -h` > 80% и `df -i` > 70%.
- **Очистка (Cleanup):** ротация старых RC-артефактов; удаление временных бэкапов после подтверждения стабильности.

## Дополнительная информация

### Связь с другими разделами знаний

- **[Изолированные среды](./air_gapped_environments.md)** — WORM, sneakernet-бандлы, Private CA, SLSA.
- **[Disaster Recovery Patterns](../../Concepts/disaster_recovery.md)** — общие паттерны DR, RPO/RTO матрицы, runbook-шаблоны.
- **[Docker: backup/restore](../../Docker/Docker_fs/docker_backup_restore.md)** — детальные процедуры бэкапа volumes и образов.
- **[Linux для CI/CD-узлов](./linux_sysadmin_for_ci.md)** — диски, systemd, лимиты, иноды для реестра и раннеров.
- **[SDLC Overview](../Core_Concepts/sdlc_overview.md)** — управление релизами, бэкапы и DR в контексте жизненного цикла.
