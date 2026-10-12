# Решения для планирования нагрузки в Kubernetes: обзор и выбор

**Актуально для:** Kubernetes 1.31+ (стандартные механизмы); версии инструментов — в соответствующих файлах

## Определения

* **Планирование (Scheduling)** — процесс распределения подов по узлам кластера. Стандартный компонент — `kube-scheduler`: на основе меток, ресурсов и политик он выбирает подходящий узел для пода.
* **Gang scheduling** — паттерн «все или ничего»: группа подов запускается одновременно или не запускается вовсе. Критичен для распределённого обучения ML/HPC.
* **Дефрагментация ресурсов** — консолидация подов на меньшем числе узлов для высвобождения целых узлов под крупные задания.
* **Bin-packing** — стратегия оценки узлов, предпочитающая более загруженные узлы (упаковка); противоположность — равномерное распределение (spread).

---

## Основные концепции

### Эволюция потребностей: от одной ноды к enterprise

Типичная траектория роста ML-инфраструктуры и механизмы, которые включаются на каждом этапе:

| Этап | Проблема | Механизм |
|------|----------|----------|
| Старт | Сервис не стартует — не запрошены GPU | `resources.limits: nvidia.com/gpu` |
| Несколько GPU | Модель работает только на определённом железе, попадает не туда | `nodeSelector` / `nodeAffinity` |
| Разнообразие GPU | Жёсткий выбор конкретной карты, простаивают остальные | `nodeAffinity` с `preferred` + весами (гибкий выбор) |
| Эксперименты vs прод | Эксперименты тормозят продакшн, страдает SLA | `podAntiAffinity` → `taints`/`tolerations` |
| Несколько ДЦ | Падение одной зоны убивает весь сервис | `topologySpreadConstraints` |
| Дефицит GPU | Эксперименты заняли все GPU, клиентский инференс ждёт | `PriorityClass` + preemption |
| Фрагментация | На каждой ноде занято мало GPU из 8, крупное задание не влезает | Descheduler (консолидация) |
| Разные паттерны нагрузки | Инференс — равномерно, обучение — плотно | Профили `KubeSchedulerConfiguration` |
| Координированные задания | Часть подов запустилась, остальные ждут, ресурсы захвачены | JobSet / Volcano / Kueue (gang scheduling) |
| Много команд | Одна команда монополизирует GPU | Kueue / YuniKorn (иерархические квоты) |
| Максимум от GPU | 8 GPU раскиданы по 4 нодам, обучение медленное | KAI Scheduler (TAS, NVLink-домены) |

### Стандартные механизмы (встроенные в Kubernetes)

Подробно описаны в соответствующих файлах:

* **NodeSelector / NodeAffinity** — выбор узлов по меткам (`required` — жёстко, `preferred` + `weight` — мягко). См. [Affinity](./affinity.md).
* **Pod Anti-Affinity** — размещение относительно других подов. См. [Affinity](./affinity.md).
* **Taints / Tolerations** — резервирование ноды под определённые типы нагрузок. См. [Taints и Tolerations](./taints_and_tolerations.md).
* **TopologySpreadConstraints** — распределение подов по топологическим ключам (зоны, ноды) с контролем перекоса `maxSkew`. См. [Affinity](./affinity.md).
* **PriorityClass + Preemption** — приоритеты заданий и вытеснение низкоприоритетных подов при нехватке ресурсов. См. [PriorityClass](../Concepts/priorityclass.md).
* **KubeSchedulerConfiguration** — перенастройка стандартного планировщика: плагины, стратегии оценки, профили для разных типов нагрузки. См. [Kube-scheduler](../Concepts/kube_scheduler.md).

**Ключевое различие:** `podAntiAffinity` — размещение **относительно других подов**; `taints/tolerations` — **резервирование ноды** под тип нагрузки.

### Дополнительные компоненты

* **Descheduler** — периодически анализирует размещение и выселяет поды, нарушающие политики или создающие перекос, для перепланирования. См. [Descheduler](../Autoscaling/descheduler.md).
* **JobSet** — координация групп взаимосвязанных Job (мастер + воркеры), All-or-Nothing жизненный цикл. См. [Job и CronJob](../Base/job.md).
* **Volcano** — фреймворк для HPC/batch: gang scheduling, приоритетные очереди, fair sharing. См. [Volcano](../Autoscaling/on_premise_autoscaling.md#volcano-для-batch-нагрузок).
* **Kueue** — очереди и квоты (ClusterQueue/LocalQueue/ResourceFlavor), gang scheduling через удержание заданий, разделение GPU между командами. См. [Kueue](./kueue.md).
* **Apache YuniKorn** — иерархические очереди с guaranteed/max, reservation, ACL, gang scheduling. См. [YuniKorn](./yunikorn.md).
* **KAI Scheduler** — GPU-планировщик NVIDIA: topology-aware scheduling (NVLink-домены), bin-packing, fairshare. См. [KAI Scheduler](./kai_scheduler.md).
* **Koordinator** — QoS-based scheduling: колокация microservices/AI/big data, overcommitment, GPU-шаринг (`koordinator.sh/gpu-core`, `koordinator.sh/gpu-memory-ratio`), интеграция с HAMi для изоляции. См. [Koordinator](https://koordinator.sh/).
* **HAMi** — GPU-виртуализация (time-slicing + изоляция видеопамяти/ядер, dynamic MIG). См. [Шеринг GPU](./gpu_sharing.md).

---

## Матрица выбора решения

### По основной проблеме

| Основная проблема | Решение |
|-------------------|---------|
| Большинство ML-нагрузок, старт | Стандартный планировщик + Node Affinity / Taints / TSC |
| Разные паттерны использования (инференс vs обучение) | Профили `KubeSchedulerConfiguration` |
| Фрагментация, перекос размещения | Descheduler |
| Координированные задания (мастер + воркеры) | JobSet |
| Квоты, разделение ресурсов между командами, приоритизация | Kueue (простая настройка, комбинируется с JobSet) |
| Распределённые тренировки, gang scheduling, приоритетные очереди | Volcano |
| Сложная иерархия доступа, квоты, reservation, ACL | Apache YuniKorn |
| Максимальная производительность GPU, топология NVLink | KAI Scheduler (TAS) |

### Сравнительная таблица

| Решение | Специализация | Сложность настройки | Масштаб |
|---------|---------------|---------------------|---------|
| Стандартный планировщик + конфигурация | Гибкая настройка без новых компонентов | Простая | Любой |
| Descheduler | Дефрагментация и ребалансировка | Простая | Любой |
| JobSet | Координированные задания, управление группами | Простая | Средний кластер |
| Kueue | Квоты, очереди, приоритизация, разделение ресурсов | Простая–средняя | Средний кластер |
| Volcano | Gang scheduling, приоритетные очереди, fair sharing | Средняя | Большие распределённые задания |
| Apache YuniKorn | Иерархические очереди, reservation, ACL | Высокая | Крупный enterprise |
| KAI Scheduler | Топологическая оптимизация GPU, bin-packing | Средняя | Крупные GPU-кластеры |
| Koordinator | Колокация нагрузок, GPU-шаринг, overcommitment | Средняя | Гибридные кластеры |

### Выбор планировщика для GPU-кластера (критерии из практики)

Нативный `kube-scheduler` с `nvidia.com/gpu` годится для небольших кластеров, но при одновременном деплое нескольких GPU-ворклоадов возникает гонка за видеокартами («кто первый съел, тот и прав»). Критерии выбора специализированного планировщика: гарантия ресурсов (квоты на команду), preemption, gang scheduling, очереди с квотами, мониторинг. Финалисты практики GPU-инференса — Kueue и Koordinator; выбран Kueue как более зрелый. См. [GPU-инференс: автоскейлинг](../Autoscaling/gpu_inference_autoscaling.md) и [Шеринг GPU](./gpu_sharing.md).

### Рекомендации по внедрению

1. **Начинайте с простого**: для большинства ML-нагрузок хватит стандартного планировщика с Node Affinity, Taints/Tolerations и TopologySpreadConstraints.
2. **Отдельный профиль планировщика для каждого нового паттерна** использования нагрузки (см. [профили](../Concepts/kube_scheduler.md#сценарий-3-изоляция-сред-через-scheduler-profiles)).
3. **JobSet + Kueue** как промежуточный шаг: комбинация значительно проще полноценного кастомного планировщика и часто закрывает эксплуатационные потребности.
4. **Выбирайте специализированный инструмент по основной проблеме** (матрица выше), а не «самый мощный».
5. **Комбинируйте при необходимости**: в сложных системах можно использовать несколько планировщиков для разных типов задач (multi-scheduler).
6. **Тестируйте на dev/stage** перед применением в production; регулярно пересматривайте конфигурацию — паттерны использования нагрузок меняются.
7. **Все изменения должны быть обоснованы** реальными потребностями и измеримой эффективностью использования ресурсов (или измеримым упрощением управления).

---

## Практические сценарии

### Профили планировщика для разных типов нагрузки

Разные типы нагрузки требуют разных стратегий: инференс — равномерное распределение (spread), обучение — плотная упаковка (bin-packing), эксперименты — без особых требований. Решает `KubeSchedulerConfiguration` с несколькими профилями:

```yaml
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
profiles:
# Инференс: равномерное распределение + учёт локальности образов
- schedulerName: inference-scheduler
  pluginConfig:
  - name: NodeResourcesFit
    args:
      scoringStrategy:
        type: LeastAllocated
        resources:
        - name: cpu
          weight: 1
        - name: memory
          weight: 1
  - name: ImageLocality
    args: {}
# Обучение: плотная упаковка в скопе GPU-ресурсов
- schedulerName: training-scheduler
  pluginConfig:
  - name: NodeResourcesFit
    args:
      scoringStrategy:
        type: MostAllocated
        resources:
        - name: nvidia.com/gpu
          weight: 2
        - name: cpu
          weight: 1
```

Привязка пода к профилю — через `spec.schedulerName`. Подробности о плагинах и стратегиях — в [Kube-scheduler](../Concepts/kube_scheduler.md).

### Тестирование конфигурации планировщика без кластера

Перед применением конфигурации в production проверьте её в **kube-scheduler-simulator** (проект kubernetes-sigs) — веб-симулятор планировщика:

* Создаются/редактируются Nodes, Pods, PV/PVC, StorageClasses, PriorityClasses через YAML;
* Подключается произвольный `KubeSchedulerConfiguration` (переменная окружения `KUBE_SCHEDULER_CONFIG_PATH`, влияют поля `.profiles`);
* Для каждого пода видны результаты **каждого Filter-плагина**, **каждого Score-плагина** и итоговый балл по узлам;
* Симулятор работает на фейковом кластере **KWOK** (Kubernetes WithOut Kubelet) — Kubernetes без kubelet;
* Запуск: `make docker_build_and_up` в репозитории, доступ на `http://localhost:3000`;
* Поддерживаются out-of-tree плагины — можно тестировать кастомные плагины планировщика.

Репозиторий: [kubernetes-sigs/kube-scheduler-simulator](https://github.com/kubernetes-sigs/kube-scheduler-simulator).

### Разделение нагрузки обучения и инференса по кластерам

Вопрос из практики: где держать train-ноды относительно продакшн-кластера, если критичен отлив данных? Рекомендация из доклада: **разделять кластеры** — обучение и инференс на разных кластерах, данные перемещать явно. Это упрощает изоляцию ресурсов и квот (Kueue/YuniKorn — внутри кластера; физическое разделение — между кластерами).

---

## Дополнительная информация

### Ограничения

* Стандартный планировщик принимает решение **однократно** в момент создания пода; для коррекции уже запущенных подов нужен Descheduler.
* Gang scheduling **не встроен** в kube-scheduler: требуется плагин `coscheduling` (scheduler-plugins) или внешний фреймворк (Volcano, Kueue, YuniKorn, KAI Scheduler).
* Descheduler выселяет поды — время простоя при перепланировании; не запускайте агрессивные политики в prime-time без тестирования в staging.

### См. также

* [Kube-scheduler: планировщик подов](../Concepts/kube_scheduler.md) — механизмы, профили, метрики
* [Affinity, Anti-Affinity, TopologySpreadConstraints](./affinity.md)
* [Taints и Tolerations](./taints_and_tolerations.md)
* [PriorityClass](../Concepts/priorityclass.md)
* [Descheduler](../Autoscaling/descheduler.md)
* [JobSet](../Base/job.md)
* [Volcano](../Autoscaling/on_premise_autoscaling.md#volcano-для-batch-нагрузок)
* [Kueue](./kueue.md)
* [Apache YuniKorn](./yunikorn.md)
* [KAI Scheduler](./kai_scheduler.md)
