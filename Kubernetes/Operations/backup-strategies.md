# Резервное копирование и аварийное восстановление в Kubernetes

## Определения

*   **Резервное копирование (Backup)** — создание копии состояния кластера и данных приложений для восстановления после сбоев или кибератак.
*   **Иммутабельность (Immutability)** — свойство данных, при котором они защищены от любого изменения или удаления (даже администратором) в течение заданного срока. Реализуется через **S3 Object Lock** в режимах *Governance* (администратор может снять блокировку при наличии прав) или *Compliance* (никто, включая провайдера, не может удалить данные до истечения срока).
*   **RPO (Recovery Point Objective)** — целевая точка восстановления; максимально допустимая потеря данных, выраженная во времени (например, "не более 15 минут данных"). Для критичных БД в Kubernetes обычно реализуется через снапшоты томов в сочетании с архивацией WAL.
*   **RTO (Recovery Time Objective)** — целевое время восстановления; максимальное допустимое время простоя сервиса до его возврата в рабочее состояние.
*   **Disaster Recovery (DR)** — комплекс мер по восстановлению инфраструктуры после катастрофических сбоев (потеря всего ЦОД или региона). Теоретические паттерны описаны в **[Disaster Recovery Patterns](../../Concepts/disaster_recovery.md)**.
*   **Правило 3-2-1 в Kubernetes:**
    *   **3** копии (рабочая среда, локальный бэкап, offsite-копия в другом регионе в объектном хранилище).
    *   **2** разных провайдера/носителя (например, снапшоты СХД + экспорт в независимое объектное хранилище).
    *   **1** копия — **иммутабельная** (защищенная от удаления ransomware, например, через Object Lock с включенным версионированием).
*   **CSI CBT (Changed Block Tracking, v1.31+)** — механизм, позволяющий системе резервного копирования запрашивать у СХД только те блоки данных, которые изменились с момента последнего снимка. Существенно ускоряет инкрементальные бэкапы.

## Базовые концепции

Стратегия резервного копирования в Kubernetes разделяется на пять независимых уровней, каждый из которых требует своего подхода.

### Зачем нужны специализированные инструменты?
Kubernetes — это динамическая распределенная система. Традиционные решения (бэкап виртуальных машин или файлов) не понимают взаимосвязи между подами, сервисами, секретами и PV. Специализированные инструменты (Velero, Kasten) взаимодействуют напрямую с Kubernetes API, что позволяет:
*   **Сохранять весь стек приложения:** Конфигурации + Состояние + Данные.
*   **Автоматизировать процесс:** Планирование и очистка старых копий без ручного вмешательства.
*   **Обеспечивать консистентность:** Синхронизация создания снимка диска с состоянием объектов в etcd и выполнением хуков.
*   **Интегрироваться с CI/CD:** Управление бэкапами как кодом (GitOps).

### Уровень 1. Состояние кластера (Control Plane / etcd)
Включает все манифесты объектов (Deployments, Services, ConfigMaps, Secrets, CRD).
*   **Метод:** Снапшоты базы данных etcd.
*   **Зависимость:** Резервное копирование etcd сохраняет определения CRD, но не включает внешние данные, которыми они управляют (например, внешние БД или системы хранения).
*   **Безопасность (Secrets):** Избегайте сброса открытых секретов на диск (`kubectl get secrets -o yaml`). Они уже включены в снапшоты etcd. Если экспорт необходим, используйте шифрование (например, SOPS + KMS).
*   **Шифрование неактивных секретов (Encryption at Rest):** Рекомендуется использовать `EncryptionConfiguration` с провайдером KMS (Vault). Это гарантирует, что секреты шифруются *перед* записью в etcd.
*   **См. также:** **[Практические операции с etcd](../Concepts/etcd_operations.md)**.

### Уровень 2. Данные приложений (Persistent Volumes)
Содержимое баз данных и файловых хранилищ.
*   **Метод:** CSI Snapshots или копирование на уровне файлов (Kopia/Restic).
*   **CSI Snapshots:** Современный стандарт, позволяющий создавать мгновенные снимки на уровне СХД через Kubernetes API. Требует наличия `VolumeSnapshotClass` и `snapshot-controller`. Начиная с Kubernetes 1.30, механизмы безопасности предотвращают несанкционированное изменение режима тома (Volume Mode) при восстановлении из снимка, защищая от эксплойтов.
*   **Мониторинг здоровья (Volume Health Monitoring):** Позволяет обнаруживать повреждения данных на уровне СХД и оповещать системы бэкапа о необходимости внеплановой проверки или перехода на реплику.
*   **Логические дампы:** Инструменты уровня приложения (mysqldump, pg_dump) для обеспечения переносимости и гранулярности.
*   **См. также:** **[API снапшотов томов (Volume Snapshots)](../Storage/CSI/csi_advanced.md)**.

### Уровень 3. Декларативное состояние (GitOps)
Конфигурация инфраструктуры, описанная в коде.
*   **Компоненты:** Манифесты развертывания, Helm-чарты, файлы конфигурации в Git.
*   **Базовые ресурсы кластера (Cluster-wide):**
    *   RBAC (ClusterRoles, ClusterRoleBindings).
    *   StorageClasses, PriorityClasses.
    *   WebhookConfigurations (Validating/Mutating).
    *   APIService, IngressClasses.
*   **Базовые ресурсы Namespace:**
    *   ResourceQuotas, LimitRanges.
    *   NetworkPolicies.
    *   PodDisruptionBudgets (PDB).
*   **Концепция:** Git является **Single Source of Truth (SSoT)**. Если кластер уничтожен, его структура восстанавливается из Git (ArgoCD / Flux).
*   **Роль бэкапа:** В этой модели традиционный бэкап etcd становится "второй линией защиты". Velero используется для миграции и восстановления "живых" данных, которые не могут быть описаны в Git (например, PVC, динамические сертификаты, состояние операторов).

### Уровень 4. Консистентность приложений (Hooks)
Обеспечение целостности данных при создании снимка.
*   **Проблема:** Снимок диска работающей БД может быть неконсистентным ("битым").
*   **Решение:** Использование **Backup Hooks** (Pre-backup и Post-backup).
    *   **Pre-backup:** Команда `FLUSH TABLES WITH READ LOCK` или `checkpoint`.
    *   **Post-backup:** Разморозка файловой системы или снятие блокировок.
*   **Пример аннотации Pod для Velero:**
    ```yaml
    metadata:
      annotations:
        pre.hook.backup.velero.io/command: '["/usr/bin/pg_dump", "-U", "postgres", "-Fc", "mydb"]'
        post.hook.backup.velero.io/command: '["/usr/bin/echo", "Backup done"]'
    ```

### Уровень 5. Системные и инфраструктурные компоненты (White Spots)
*   **Service Mesh (Istio/Linkerd):** Бэкап конфигураций (Gateways, VirtualServices) через GitOps. Важно учитывать динамические состояния mTLS сертификатов и настройки трафика, хранящиеся в CRD.
*   **Мониторинг (Prometheus/Grafana):** Рекомендуется использовать **Remote Write** в масштабируемые хранилища (Thanos, Mimir, VictoriaMetrics) вместо бэкапа локальной TSDB Prometheus. Для Grafana — экспорт дашбордов и настроек источников данных в Git.
*   **Сертификаты (cert-manager):** Бэкап `Secrets` с закрытыми ключами CA и `Issuers` критичен для восстановления доверия в кластере после DR.

## Сопоставление RPO/RTO со стратегиями резервного копирования

Выбор стратегии восстановления должен основываться на бизнес-требованиях к доступности и допустимой потере данных. Более низкие показатели RPO/RTO требуют больших затрат на хранение и вычислительные ресурсы.

| Стратегия | Расписание (пример) | Типичный RPO | Типичный RTO | Примечания |
| :--- | :--- | :--- | :--- | :--- |
| **CSI Snapshots** | Каждые 15 мин. | ≤ 15 мин. | 5–30 мин. | **Tier 1.** Быстрый откат внутри региона; для DR требуется репликация в другой регион. |
| **Логический дамп** | Часовые дампы + ночной полный | ≤ 60 мин. | 30–90 мин. | Портативность; медленно для больших БД (>100GB) без дополнительной настройки. |
| **Репликация БД** | WAL/binlog + снимки | ≤ 1–5 мин. | 10–30 мин. | Низкий RPO; требует настройки failover и контроля последовательности реплик. |
| **Активный/Активный** | Синхронная репликация | ≈ 0 | 1–5 мин. | **Tier 0.** Самая высокая стоимость/сложность; лучший RTO/RPO. |

### Выбор расписания и стратегии
Для достижения бизнес-целей следуйте алгоритму:
1.  **Бизнес-цели:** Начните с определения требуемых RTO (например, 30 мин) и RPO (например, 5 мин).
2.  **Путь данных:** Выберите механизм, обеспечивающий RPO (снапшоты каждые 5–15 мин или потоковая репликация). С 2026 года стандартом де-факто является инкрементальный блочный бэкап через CSI (с поддержкой CBT).
3.  **Внешняя копия:** Настройте репликацию бэкапов в удаленный регион (Offsite) с соблюдением того же RPO.
4.  **Учения (DR Drills):** Замеряйте фактические показатели RTO/RPO во время тренировок; корректируйте частоту, инструменты или топологию до достижения цели.
5.  **Компромиссы:** Документируйте и согласовывайте с бизнесом затраты на хранилище, трафик и дополнительные кластеры.

## Сценарии катастроф в Kubernetes

План аварийного восстановления должен строиться вокруг реалистичных режимов сбоя:
*   **Сбои уровня кластера:** Поломка плоскости управления (Control Plane), повреждение etcd или полная потеря кластера.
*   **Сбои хранилища:** Масштабный сбой систем хранения, потеря доступа к дисковому массиву или программные сбои в работе СХД.
*   **Сбои приложений:** Некорректные развертывания, ошибки конфигурации или утечки ресурсов, приводящие к каскадному отказу сервисов.
*   **Региональные сбои:** Полное отключение географического региона из-за проблем с инфраструктурой или поставщиком.
*   **Операционные катастрофы:** Случайное удаление данных сотрудником или атаки программ-вымогателей (Ransomware).

## Создание эффективного плана аварийного восстановления (DRP)

Надежный план — это не статичный документ, а набор проверенных и повторяемых процессов:

1.  **Документирование процедур:** Пошаговая инструкция по восстановлению нагрузок, конфигураций и данных. Хранится в системе контроля версий и в автономном месте.
2.  **Автоматизация воссоздания кластера:**
    *   **IaC (Infrastructure as Code):** Использование Terraform/Pulumi для подготовки новых кластеров.
    *   **GitOps (Argo CD/Flux):** Автоматическое развертывание приложений из заведомо исправного состояния (SSoT). Восстановление stateless конфигураций должно идти через Git, а не через инструменты бэкапа.
3.  **Учебники (Runbooks) по восстановлению данных:** Детальные инструкции по восстановлению etcd, Persistent Volumes и данных уровня приложений (команды, доступы, пути).
4.  **Аварийное переключение (Failover) и Защита от Split-Brain:**
    *   Мультикластерные и мультирегиональные стратегии.
    *   **DNS-балансировка:** Использование ExternalDNS с внешним DNS-сервисом для автоматического перенаправления трафика.
    *   **ReadWriteOncePod (v1.31+):** Используйте этот режим доступа для критичных PVC. Он гарантирует, что при сбое и восстановлении только один под во всем кластере сможет писать в том, жестко предотвращая порчу данных (split-brain).
5.  **Тестирование:** Проведение DR-учений не реже одного раза в квартал с моделированием сбоев и сравнением фактических показателей с целевыми.

### Пример: Восстановление после сбоя региона
Сценарий: отказ региона `eu-central-1`.
*   **Второй кластер:** В `eu-west-1` с предварительно развернутыми базовыми сервисами (масштабированы в 0).
*   **Бэкапы:** Ночные снимки etcd и PV реплицируются в объектное хранилище региона `eu-west-1`.
*   **Трафик:** Политика Failover в DNS-балансировщике переключает трафик на резервный кластер при провале проверок здоровья.
*   **Восстановление:** Конвейер IaC масштабирует поды до нужного уровня за считанные минуты.

> **Совет:** При составлении списка сценариев учитывайте не только технические сбои, но и человеческий фактор (случайное удаление) и инциденты безопасности.

## Типы резервных копий в Kubernetes

Для построения надежной системы защиты необходимо комбинировать различные типы копий в зависимости от требуемых RPO/RTO.

| Тип | Что копируется | Инструменты | Применение |
| :--- | :--- | :--- | :--- |
| **Снапшот (CSI)** | Блочный уровень диска | Ceph RBD, CSI Driver, другие драйверы СХД | Мгновенный откат тома, высокая скорость. Использует `VolumeSnapshot` (уровень Namespace) и `VolumeSnapshotContent` (уровень кластера). |
| **Клонирование (CSI)** | Точная копия тома | Kubernetes API (dataSource) | Тестирование на реальных данных, Fork БД без прерывания работы оригинала. |
| **Экспорт (Export)** | Метаданные + Файлы | Velero, Kasten K10 | Миграция между кластерами, долгосрочное хранение в объектном хранилище. |
| **Логический (Dump)** | SQL/Данные приложения | pg_dump, mysqldump | Восстановление отдельных таблиц, малые БД. Гарантирует переносимость между версиями. |
| **Метаданные** | YAML-манифесты | `kubectl get -o yaml`, Velero, Git | Восстановление структуры кластера без данных PV. База для GitOps. |
| **Checkpoint/Restore (CRIU)** | Образ памяти и процесса | Kubelet (v1.30+) | *Новый метод (Beta в 1.30).* Заморозка состояния работающего контейнера в архив для мгновенного перезапуска или переноса на другой узел без повторной инициализации приложения. |

### Управление секретами из внешних источников
При использовании **External Secrets Operator (ESO)** или **CSI Secret Store Driver** (интеграция с HashiCorp Vault, внешние хранилища секретов), стратегия бэкапа меняется:
*   **Бэкап в K8s:** Необходим бэкап ресурсов `ExternalSecret` (определения того, что и откуда брать).
*   **Бэкап источника:** Основной фокус смещается на резервное копирование самого внешнего хранилища (например, Raft-снапшоты в HashiCorp Vault).
*   **Секреты-зеркала:** Если ESO синхронизирует данные в нативные `Secret` объекты, Velero сохранит их, но при восстановлении ESO может перезаписать их новыми значениями из внешнего источника.

## Выбор инструментов для резервного копирования

| Инструмент | Ключевые особенности | Лучшее применение |
| :--- | :--- | :--- |
| **Velero** | Open source, поддержка Kopia, CSI v1.15+, миграция между кластерами. | Универсальное решение, стандарт индустрии. |
| **Kasten K10** | Enterprise-функции, глубокая автоматизация политик, Multi-cluster управление. | Крупные инсталляции, строгие требования Compliance. |
| **Stash** | Оператор для БД, нативная поддержка GitOps, интеграция с Restic/Kopia. | Бэкап конкретных приложений и баз данных. |
| **Native (kubectl/etcdctl)** | Ручной экспорт YAML и снимки etcd. | Обучение, маленькие кластеры, глубокая отладка. |

### Факторы выбора:
1.  **Сложность кластера:** Для крупных сред необходимы инструменты с поддержкой политик и Multi-tenancy (Velero/Kasten).
2.  **Тип данных:** Для БД с интенсивной записью критичны Hooks и поддержка специализированных операторов (Stash). В современных СХД критична поддержка протокола CSI CBT для ускорения инкрементального бэкапа.
3.  **Среда:** Многие платформы имеют встроенную поддержку CSI-снапшотов, облегчающую работу Velero.
4.  **Compliance:** Требования к шифрованию, аудиту, автоматической проверке целостности бэкапов перед восстановлением и иммутабельности (WORM) могут потребовать корпоративных решений.

## Практические сценарии

### Резервное копирование etcd (etcdctl)
Для создания снимка в работающем кластере (online snapshot) используется `etcdctl` с указанием сертификатов:
```bash
ETCDCTL_API=3 etcdctl snapshot save snapshot.db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
```
# → Snapshot saved at snapshot.db

Для восстановления при аварии (Offline) используется **etcdutl**:
```bash
etcdutl snapshot restore snapshot.db --data-dir /var/lib/etcd-from-backup
```

### Экспорт базовых ресурсов (kubectl)
Если GitOps не используется, манифесты можно выгрузить вручную:
```bash
# Уровень кластера
kubectl get clusterroles,clusterrolebindings,storageclasses,priorityclasses,validatingwebhookconfigurations,mutatingwebhookconfigurations,apiservices,ingressclasses -o yaml > cluster-scope.yaml

# Определения Namespace и их базовые политики
kubectl get namespaces -o yaml > namespaces.yaml
kubectl get resourcequotas,limitranges,networkpolicy,pdb -A -o yaml > namespace-baselines.yaml
```

### Резервное копирование CRD и их экземпляров
```bash
# Экспорт всех CRD
kubectl get crds -o yaml > crds-backup.yaml

# Экспорт всех экземпляров (CR) для каждого CRD
for crd in $(kubectl get crd -o name | cut -d/ -f2); do
  kubectl get "$crd" -A -o yaml >> custom-resources.yaml || true
done
```

### Снапшоты томов (VolumeSnapshot)
Если провайдер СХД поддерживает CSI, можно использовать декларативный подход:
```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: mysql-data-snapshot
  namespace: database
spec:
  volumeSnapshotClassName: csi-snapshot-class
  source:
    persistentVolumeClaimName: mysql-pvc
```
# → Создает снимок PersistentVolume на уровне СХД.

### Использование Velero (v1.15+ с Kopia)
Velero является основным инструментом для резервного копирования, обеспечивая сохранение метаданных и данных томов.

**Установка с uploader-типом Kopia (рекомендуется):**
```bash
velero install \
    --provider generic \
    --plugins velero/velero-plugin-for-aws:v1.13.0 \
    --bucket velero-backups \
    --secret-file ./credentials-velero \
    --use-node-agent \
    --uploader-type kopia
```

Подробное описание см. в:
*   **[Обзор Velero: Резервное копирование Kubernetes](../ToolsUtilities/velero-overview.md)**

### Кросс-кластерное восстановление и миграция
При восстановлении в другой кластер (Disaster Recovery) необходимо учитывать:
1.  **StorageClass Mapping:** Имена StorageClass могут различаться. Используйте `Resource Modifiers` в Velero для замены классов "на лету".
2.  **Версии API:** Объекты, созданные для старых версий K8s, могут требовать конвертации (например, Ingress `extensions/v1beta1` -> `networking.k8s.io/v1`).
3.  **DNS и Трафик:** После восстановления требуется обновление внешних DNS-записей, LoadBalancer IP и Ingress-контроллеров.
4.  **Частичная миграция StatefulSet (v1.31+):** Использование `spec.ordinals.start` позволяет мигрировать поды StatefulSet частями (например, сначала поды 3-5, потом 0-2), минимизируя простой тяжелых баз данных при миграции между пространствами имен или кластерами.

### Обеспечение безопасности бэкапов
1.  **Шифрование:** Все бэкапы в S3 должны шифроваться через Server-Side Encryption (SSE-KMS) или на стороне клиента.
2.  **Шифрование неактивных секретов:** Настройка `EncryptionConfiguration` в API-сервере гарантирует защиту секретов в снапшотах etcd.
3.  **RBAC:** Доступ к CRD бэкапа должен быть ограничен только администраторами безопасности.
4.  **Иммутабельность (WORM):** Использование **S3 Object Lock** предотвращает удаление бэкапов программами-вымогателями даже при компрометации учетных данных администратора.
5.  **Блокировка изменения VolumeMode (v1.30+):** Kubernetes теперь по умолчанию запрещает менять режим тома (с блока на файловую систему) при восстановлении, предотвращая атаки на уровне гипервизора/СХД.

## Рекомендации (Best Practices)

*   **Автоматизация:** Использование расписаний (Schedules) для исключения человеческого фактора.
*   **Регулярная проверка (Restore Test):** Бэкап считается существующим только после успешного тестового восстановления. Современные системы могут делать это автоматически.
*   **Политика хранения (Retention Policy):** Установите четкие сроки хранения (например, 7 дней для ежедневных снапшотов, 1 год для ежемесячных экспортов).
*   **Документирование:** Поддерживайте актуальный **Disaster Recovery Plan (DRP)** с пошаговыми инструкциями.
*   **Мониторинг:** Настройка алертов на сбои бэкапов и проверку целостности (метрики Velero на порту 8085).

## Советы для собеседования

**Вопрос:** Почему важно выполнять резервное копирование физических файлов (PV) отдельно от etcd?
**Ответ:** etcd хранит только конфигурацию и состояние (метаданные), но не сами данные внутри томов. Потеря PV означает потерю бизнес-данных (БД, файлы пользователей), которые невозможно восстановить только из etcd. Полная стратегия DR должна включать оба компонента.

**Вопрос:** В чем преимущества и недостатки логических дампов по сравнению со снимками CSI?
**Ответ:** 
*   **Логические дампы (pg_dump, mysqldump):** 
    *   *Плюсы:* Переносимость между облаками/версиями БД, возможность восстановления отдельных объектов. 
    *   *Минусы:* Медленные на больших объемах, нагрузка на CPU, риск неконсистентности без блокировок.
*   **Снимки CSI (VolumeSnapshots):** 
    *   *Плюсы:* Мгновенное создание, минимальная нагрузка на систему. Интеграция с CBT (v1.31+) для ультрабыстрых инкрементов.
    *   *Минусы:* Привязка к вендору СХД, ограниченная переносимость между провайдерами без шага экспорта.
*   **Best Practice:** Использовать снимки CSI для быстрого восстановления (RTO) и логические дампы для долгосрочного архива и миграции.

**Вопрос:** Каков правильный порядок восстановления при полной потере кластера?
**Ответ:** Рекомендуемый порядок действий (**Infrastructure First**):
1.  **CRD** и инфраструктура кластера (RBAC, StorageClasses, WebhookConfigurations).
2.  **Пространства имен** и их базовые политики (Quotas, NetPol, PDB).
3.  **Рабочие нагрузки (Workloads)**: Деплой stateless-приложений через GitOps.
4.  **Данные приложений**: Подключение PV из снапшотов или восстановление БД из дампов. Запуск stateful-приложений.
5.  **Верификация**: Проверка консистентности и доступности сервисов.

**Вопрос:** Зачем нужны Pre-backup хоки?
**Ответ:** Для обеспечения **Application Consistency**. Они позволяют "заморозить" запись в базу данных перед тем, как CSI-драйвер сделает снимок диска, что гарантирует отсутствие поврежденных транзакций при восстановлении.

## Проверка целостности и валидация бэкапов

Бэкап не считается надежным до успешного тестового восстановления. Включите валидацию в pipeline:

### Верификация снапшота etcd

```bash
# 1. Проверка целостности файла снапшота
etcdutl snapshot status /backup/etcd-snapshot.db --write-out=table
# → hash: ..., revision: ..., total size: ..., ...

# 2. Dry-run восстановления в isolated окружение
etcdutl snapshot restore /backup/etcd-snapshot.db \
  --data-dir /var/lib/etcd-restored \
  --name restore-test \
  --initial-cluster restore-test=https://127.0.0.1:2380 \
  --initial-cluster-token restore-test

# 3. Запуск etcd из восстановленных данных и проверка целостности ключей
etcd --data-dir /var/lib/etcd-restored \
  --listen-client-urls https://127.0.0.1:2379 \
  --advertise-client-urls https://127.0.0.1:2379 \
  --listen-peer-urls https://127.0.0.1:2380 \
  --initial-advertise-peer-urls https://127.0.0.1:2380 \
  --initial-cluster restore-test=https://127.0.0.1:2380 \
  --initial-cluster-token restore-test \
  --cert-file /etc/kubernetes/pki/etcd/server.crt \
  --key-file /etc/kubernetes/pki/etcd/server.key

# 4. Проверка количества ключей
etcdctl get /registry --prefix --keys-only | wc -l
```

### Верификация Velero-бэкапа

```bash
# 1. Проверка статуса последнего бэкапа
velero backup describe <backup-name> --details
# → Phase: Completed, Errors: 0

# 2. Проверка логов плагинов на ошибки
velero backup logs <backup-name> | grep -i error
# → пустой вывод = отсутствие ошибок

# 3. Тестовое восстановление в отдельный namespace
velero restore create --from-backup <backup-name> \
  --namespace-mappings production:restore-test

# 4. Проверка восстановленных ресурсов
kubectl get all -n restore-test
kubectl get pvc -n restore-test
```

### Автоматическая проверка через CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-backup-verify
  namespace: kube-system
spec:
  schedule: "0 6 * * 1,4"  # Пн и Чт в 06:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: verify
            image: bitnami/etcd:3.5
            command:
            - /bin/sh
            - -c
            - |
              etcdutl snapshot status /backup/etcd-snapshot.db --write-out=table || exit 1
              echo "Backup verification passed: $(date)"
          restartPolicy: Never
          hostPath:
          - path: /backup
            mountPath: /backup
```

## Резервное копирование etcd: расширенный ранбук

### Предварительные проверки (Pre-flight)

Перед созданием снапшота убедитесь, что кластер в стабильном состоянии:

```bash
# 1. Здоровье etcd (кворум и лидер)
etcdctl endpoint health --cluster -w table
etcdctl endpoint status --cluster -w table
# → Все члены healthy, RAFT TERM совпадает

# 2. Свободное место на диске (>= 2x от размера БД)
df -h /var/lib/etcd
etcdctl endpoint status --write-out=json | jq '.[].Status.dbSize' | numfmt --to=iec
# → Убедитесь, что свободно минимум 2x от dbSize

# 3. Отсутствие активных миграций или массовых операций
kubectl get pods -A | grep -Ev 'Running|Completed' | wc -l
# → 0 перед началом бэкапа
```

### Создание снапшота с именованием и ротацией

```bash
#!/bin/bash
# /usr/local/bin/etcd-backup.sh
set -euo pipefail

BACKUP_DIR="/backup/etcd"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d-%H%M)
SNAPSHOT="${BACKUP_DIR}/etcd-${TIMESTAMP}.db"
ENDPOINTS="https://127.0.0.1:2379"
CACERT="/etc/kubernetes/pki/etcd/ca.crt"
CERT="/etc/kubernetes/pki/etcd/server.crt"
KEY="/etc/kubernetes/pki/etcd/server.key"

mkdir -p "${BACKUP_DIR}"

# Создание снапшота
ETCDCTL_API=3 etcdctl snapshot save "${SNAPSHOT}" \
  --endpoints="${ENDPOINTS}" \
  --cacert="${CACERT}" \
  --cert="${CERT}" \
  --key="${KEY}"

# Проверка целостности
ETCDCTL_API=3 etcdctl snapshot status "${SNAPSHOT}" --write-out=table

# Ротация (удаление снапшотов старше RETENTION_DAYS)
find "${BACKUP_DIR}" -name "etcd-*.db" -type f -mtime +${RETENTION_DAYS} -delete

# Ротация WAL (опционально, для экономии места)
# etcdctl defrag --cluster  # Выполнять редко, после крупных удалений
```

```bash
# Запуск вручную
chmod +x /usr/local/bin/etcd-backup.sh
/usr/local/bin/etcd-backup.sh

# Планировщик (cron)
# 0 2 * * * /usr/local/bin/etcd-backup.sh >> /var/log/etcd-backup.log 2>&1
```

### Восстановление из снапшота (Offline)

```bash
# 1. Остановка kube-apiserver (Static Pod)
mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/

# 2. Ожидание остановки Pod
crictl ps | grep kube-apiserver
# → пока процесс завершится

# 3. Остановка etcd на всех control-plane узлах (кроме одного)
systemctl stop etcd

# 4. Восстановление на выбранном узле
ETCDCTL_API=3 etcdutl snapshot restore /backup/etcd-20260830-0200.db \
  --name master \
  --initial-cluster "master=https://10.0.1.10:2380" \
  --initial-advertise-peer-urls "https://10.0.1.10:2380" \
  --data-dir /var/lib/etcd-restored

# 5. Замена данных
systemctl stop etcd
rm -rf /var/lib/etcd/*
cp -r /var/lib/etcd-restored/* /var/lib/etcd/
chown -R etcd:etcd /var/lib/etcd

# 6. Запуск etcd
systemctl start etcd

# 7. Возврат kube-apiserver
mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/

# 8. Проверка
kubectl get nodes
kubectl get pods -A
```

## Автоматизация и планирование

### Velero: Scheduled Backups

```yaml
# daily-app-backup.yaml
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: production-daily
  namespace: velero
spec:
  schedule: "0 2 * * *"  # Каждый день в 02:00
  template:
    includedNamespaces:
      - production
      - staging
    excludedResources:
      - events
      - backups.velero.io
    ttl: 168h  # Хранить 7 дней
    defaultVolumesToFsBackup: false  # Использовать CSI Snapshots
    snapshotVolumes: true
```

### Кросс-кластерное восстановление: Resource Modifiers

При восстановлении в кластер с другой конфигурацией СХД используйте `Resource Modifiers`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: restore-modifiers
  namespace: velero
data:
  rules.yaml: |
    - conditions:
        groupResource: persistentvolumeclaims
      patches:
        - operation: replace
          path: /spec/storageClassName
          value: high-perf-ssd
    - conditions:
        groupResource: pods
      patches:
        - operation: replace
          path: /spec/nodeName
          value: ""
```

```bash
velero restore create --from-backup prod-backup \
  --resource-modifier-configmap restore-modifiers \
  --namespace-mappings production:production-restore
```

### Retention Policies и очистка

```bash
# Velero: удаление бэкапов старше 30 дней
velero backup create --include-namespaces production \
  --ttl 720h0m0s \
  --schedule "0 2 * * *"

# etcd: ротация снапшотов (через cron + find)
find /backup/etcd -name "*.db" -mtime +30 -delete

# Логические дампы: политика через cron
0 3 * * * pg_dump -U postgres mydb | gzip > /backup/pg/$(date +\%Y\%m\%d).sql.gz
find /backup/pg -name "*.sql.gz" -mtime +7 -delete
```

## Хранилище и Persistent Volumes

### Выбор метода бэкапа по типу СХД

| Тип СХД | Рекомендуемый метод | Примечания |
| :--- | :--- | :--- |
| **Блочное (iSCSI, FC, NVMe)** | CSI Snapshots + CBT | Быстрый, но привязка к вендору. Используйте экспорт для миграции. |
| **Файловое (NFS, GlusterFS)** | Файловый бэкап (Kopia/Restic) | CSI Snapshots могут не поддерживаться. |
| **Локальный (Local PV)** | Файловый бэкап или логический дамп | Снапшоты зависят от драйвера. Для RWO критичен планирование отключения узла. |
| **Объектное (MinIO, S3-совместимое)** | Нативная репликация + Velero | Данные уже в объектном хранилище; достаточно репликации бакета. |

### Резервное копирование Local PV

```bash
# На узле с Local PV: создание архива через Kopia
kopia snapshot create /mnt/local-pv \
  --host=node-1 \
  --compression=zstd

# Или через Restic
restic -r /backup-repo backup /mnt/local-pv \
  --tag local-pv-mysql
```

### Проверка здоровья PVC перед бэкапом

```bash
# Проверка, что PVC подключен и ReadWrite
kubectl get pvc -A -o jsonpath='{range .items[*]}{.metadata.namespace} {.metadata.name} {.status.phase} {.status.accessModes[0]} {"\n"}{end}'

# Проверка состояния VolumeSnapshotClass
kubectl get volumesnapshotclass
# → Должен быть класс с режимом Delete или Retain
```

## Восстановление и валидация

### Пошаговый порядок восстановления кластера (Infrastructure First)

```bash
# Этап 1: Восстановление CRD и кластерной инфраструктуры
kubectl apply -f cluster-scope.yaml

# Этап 2: Создание namespace и базовых политик
kubectl apply -f namespaces.yaml
kubectl apply -f namespace-baselines.yaml

# Этап 3: Восстановление workloads (stateless)
kubectl apply -f gitops-manifests/
# Или через ArgoCD/Flux

# Этап 4: Восстановление данных (PV)
velero restore create --from-backup <backup-name> \
  --namespace-mappings production:production

# Для StatefulSet с локальными томами: восстановите данные через
# логический дамп или файловый бэкап перед запуском подов

# Этап 5: Верификация
kubectl get pods -A
kubectl get pvc -A
kubectl get svc -A
```

### Валидация после восстановления

```bash
# 1. Проверка готовности всех подов
kubectl wait --for=condition=Ready pod --all -A --timeout=300s

# 2. Проверка PDB (не нарушены ли minAvailable)
kubectl get pdb -A

# 3. Проверка эндпоинтов (сервисы имеют адреса)
kubectl get endpoints -A | grep -v '<none>'

# 4. Проверка времени восстановления (RTO)
# Замеряйте от момента объявления аварии до полной готовности сервисов

# 5. Проверка целостности данных (приложение)
kubectl exec -n production deploy/api -- curl -s http://localhost:8080/health | jq .
# → {"status":"ok"}
```

## Диагностика проблем резервного копирования

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `etcdctl snapshot save` зависает | Высокая нагрузка на etcd или проблемы с сетью | Проверьте `etcdctl endpoint status`; выполните в часы низкой нагрузки |
| `velero backup` в `PartiallyFailed` | Отсутствует `VolumeSnapshotClass` или CSI-драйвер не отвечает | Проверьте `kubectl get volumesnapshotclass`; убедитесь, что CSI-драйвер работает на всех узлах |
| `drain` «застревает» на PDB | `minAvailable` слишком высокий для текущего размера кластера | Увеличьте количество реплик или временно расширьте кластер перед drain |
| `VolumeSnapshot` не создается | PVC в состоянии `Lost` или `Terminating` | Проверьте статус PVC; при необходимости удалите финализаторы |
| `velero restore` падает с `already exists` | Ресурс уже существует в целевом namespace | Используйте `--existing-resource-policy=update` или очистите namespace |
| `etcdutl snapshot restore` падает с `cluster token mismatch` | Попытка восстановить два кластера из одного снапшота | Используйте уникальный `--initial-cluster-token` для каждого нового кластера |

### Диагностика на уровне хоста (Sysadmin)

```bash
# 1. Проверка состояния etcd (systemd)
systemctl status etcd
journalctl -u etcd -f --since "30 minutes ago"

# 2. Проверка TLS-сертификатов (срок действия)
openssl x509 -in /etc/kubernetes/pki/etcd/server.crt -noout -dates
openssl x509 -in /etc/kubernetes/pki/etcd/ca.crt -noout -dates

# 3. Проверка портов (etcd слушает на 2379 и 2380)
ss -tlnp | grep -E '2379|2380'

# 4. Проверка сетевой доступности между control-plane узлами
for node in cp-1 cp-2 cp-3; do
  nc -zv ${node} 2380
done

# 5. Проверка объема WAL и размера БД
du -sh /var/lib/etcd/member/wal
du -sh /var/lib/etcd/member/snap
```

## Дополнительная информация

*   **[Поиск и устранение неисправностей в Kubernetes](../Troubleshooting/troubleshooting_overview.md)** — следующий этап эксплуатации после настройки защиты: диагностика и решение проблем.
*   **[Обзор Velero](../ToolsUtilities/velero-overview.md)** — основной инструмент бэкапа.
*   **[Продвинутые возможности CSI](../Storage/CSI/csi_advanced.md)** — детали работы со снапшотами томов.
*   **[Стратегии резервного копирования БД](../../Databases/Concepts/backups.md)** — теоретические основы (3-2-1, PITR).
