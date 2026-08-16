# Гексагональная архитектура (Порты и Адаптеры)

## Определения

**Гексагональная архитектура (Hexagonal Architecture)**, также известная как **архитектура портов и адаптеров (Ports and Adapters)**, — это архитектурный паттерн, направленный на изоляцию доменной (бизнес) логики от внешних зависимостей. Паттерн обеспечивает независимость ядра приложения от технологий передачи данных (HTTP, gRPC, CLI) и способов их хранения (SQL, NoSQL, In-memory).

**Ключевая идея:** Бизнес-логика («Ядро») не знает о существовании внешнего мира. Она взаимодействует с ним через абстрактные интерфейсы («Порты»), реализация которых («Адаптеры») подключается извне через механизм инверсии зависимостей (Dependency Inversion).

## Предварительные требования

Для успешного применения паттерна необходимо владение следующими темами:
*   **Принципы SOLID:** В особенности **D** (Dependency Inversion).
*   **Domain-Driven Design (DDD):** Базовое понимание сущностей (Entities) и агрегатов (Aggregates).
*   **Внедрение зависимостей (Dependency Injection):** Навык работы с DI-контейнерами или ручной сборкой зависимостей.

## Базовые концепции

### Ключевые компоненты

- **Ядро (Core / Domain):**
  - Содержит чистую бизнес-логику, сущности (Entities), доменные службы и правила.
  - Это самая стабильная часть приложения, не зависящая от библиотек ввода-вывода или фреймворков.
  - Использует тактические паттерны **DDD**: агрегаты, стоимостные объекты (Value Objects).
- **Порты (Ports):**
  - Это интерфейсы, определенные внутри Ядра.
  - **Входящие порты (Driving Ports):** Интерфейсы, через которые внешние системы управляют Ядром (Use Cases).
  - **Исходящие порты (Driven Ports):** Интерфейсы, через которые Ядро запрашивает данные или отправляет уведомления (Repositories, Clients).
- **Адаптеры (Adapters):**
  - **Входящие адаптеры (Driving Adapters):** Преобразуют внешние запросы в вызовы Ядра. Примеры: REST-контроллер, Kafka Consumer.
  - **Исходящие адаптеры (Driven Adapters):** Реализуют исходящие порты, инкапсулируя работу с технологией. Примеры: PostgreSQL Repository, S3 Client.

### Сравнение с многослойной архитектурой

В традиционной многослойной архитектуре (N-tier) зависимости направлены сверху вниз: `Presentation → Business → Data`. Это делает бизнес-логику зависимой от базы данных. 
Гексагональная архитектура «выворачивает» эту схему: и Presentation, и Data зависят от Ядра, находясь на одном уровне абстракции по отношению к нему.

## Практическая реализация

### Пример реализации на TypeScript

**1. Исходящий порт (Repository Interface):**
```typescript
// domain/ports/UserRepository.ts
export interface UserRepository {
  save(user: User): Promise<void>;
  findById(id: string): Promise<User | null>;
}
```

**2. Ядро (Use Case):**
```typescript
// application/CreateUserUseCase.ts
import { UserRepository } from "../domain/ports/UserRepository";
import { User } from "../domain/models/User";

export class CreateUserUseCase {
  constructor(private userRepo: UserRepository) {}

  async execute(name: string, email: string): Promise<void> {
    const user = new User(name, email);
    // Бизнес-логика валидации и обработки
    await this.userRepo.save(user);
  }
}
```

**3. Исходящий адаптер (PostgreSQL Implementation):**
```typescript
// infrastructure/db/PostgresUserAdapter.ts
import { UserRepository } from "../../domain/ports/UserRepository";
import { PrismaClient } from "@prisma/client";

export class PostgresUserAdapter implements UserRepository {
  constructor(private prisma: PrismaClient) {}

  async save(user: User): Promise<void> {
    await this.prisma.user.create({ data: { ...user } });
  }
  // ... findById
}
```

**4. Входящий адаптер (Express Controller):**
```typescript
// presentation/http/UserController.ts
export class UserController {
  constructor(private createUserUseCase: CreateUserUseCase) {}

  async handle(req: Request, res: Response) {
    const { name, email } = req.body;
    await this.createUserUseCase.execute(name, email);
    res.status(201).send();
  }
}
```

### Валидация архитектуры (ArchUnit)

Для предотвращения «протечки» инфраструктуры в ядро в CI/CD пайплайнах используются архитектурные тесты. 

**Пример на ArchUnit (Java):**
```java
classes().that().resideInAPackage("..domain..")
    .should().onlyBeAccessed().byAnyPackage("..domain..", "..application..", "..infrastructure..")
    .check(importedClasses);

classes().that().resideInAPackage("..domain..")
    .should().notDependOnClassesWithinPackages("..infrastructure..")
    .check(importedClasses);
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Domain содержит ORM-аннотации** | Стремление сократить код маппинга. | Использовать отдельные модели для БД и Домена. Маппинг делать в адаптере. |
| **Циклические зависимости** | Неправильное распределение интерфейсов. | Убедиться, что интерфейсы портов определены в слое Домена или Application. |
| **Толстые контроллеры** | Логика координации осталась в адаптере. | Перенести логику в Use Case (Application layer). |
| **Сложность тестирования портов** | Порт слишком широкий (Fat Interface). | Применить Interface Segregation Principle (ISP). |

## Лучшие практики

1.  **Маппинг всегда в адаптерах:** Ядро никогда не должно импортировать ничего из `infrastructure` или `presentation`.
2.  **DTO для каждого уровня:** Используйте Request DTO для контроллеров и Domain Entities для ядра. Это предотвращает случайное изменение API при рефакторинге логики.
3.  **Dependency Injection:** Используйте DI-контейнеры (InversifyJS, NestJS DI, Spring IoC) для автоматизации сборки гексагона.
4.  **Unit-тестирование Ядра:** Ядро должно тестироваться без запуска БД или серверов, используя простые In-memory моки портов.

## Современные тренды (2025–2026)

*   **Edge Computing и WASM:** Благодаря изоляции ядра, его можно компилировать в WebAssembly и запускать на граничных узлах (CDN), подключая специфические адаптеры для каждого облачного провайдера.
*   **Hexagonal Serverless:** Ядро упаковывается в AWS Lambda / Google Cloud Run, а порты позволяют легко переключаться между разными триггерами (HTTP, EventBridge, Pub/Sub) без изменения кода функции.
*   **Архитектурный Linter:** Автоматизация проверки правил зависимостей становится обязательным этапом Pre-commit хуков.

## Дополнительная информация

### См. также
*   **[Монолит и микросервисы](./monolith_vs_microservices.md)** — архитектурные подходы и выбор стратегии.
*   **[Инфраструктура как код (IaC)](./iac_overview.md)** — автоматизация развертывания адаптеров.
*   **[Событийная архитектура](../Kafka/kafka_overview.md)** — использование брокеров сообщений как адаптеров.
