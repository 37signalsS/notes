# Гексагональная архитектура (Порты и Адаптеры)

## Определения

**Гексагональная архитектура (Hexagonal Architecture)**, также известная как **архитектура портов и адаптеров (Ports and Adapters)**, — это архитектурный паттерн, направленный на изоляцию доменной (бизнес) логики от внешних зависимостей. Паттерн обеспечивает независимость ядра приложения от технологий передачи данных (HTTP, gRPC, CLI) и способов их хранения (SQL, NoSQL, In-memory).

**Ключевая идея:** Бизнес-логика («Ядро») не знает о существовании внешнего мира. Она взаимодействует с ним через абстрактные интерфейсы («Порты»), реализация которых («Адаптеры») подключается извне через механизм инверсии зависимостей (Dependency Inversion).

### Историческая справка
Паттерн был предложен Алистером Кокбурном (Alistair Cockburn) в 2005 году как ответ на проблему тестирования приложений с привязкой к базам данных и графическим интерфейсам. Кокбурн заметил, что приложения, напрямую зависящие от инфраструктуры, невозможно тестировать изолированно. Решением стало разделение на ядро с чистой бизнес-логикой и внешние компоненты, подключаемые через интерфейсы.

### Ключевые преимущества
1. **Тестируемость:** Ядро тестируется без запуска инфраструктуры (БД, HTTP-серверов, файловой системы).
2. **Заменяемость:** Адаптеры можно заменять без изменения бизнес-логики (например, переключение с PostgreSQL на MySQL).
3. **Независимость от фреймворков:** Ядро не зависит от Django, Spring, Express или других фреймворков.
4. **Параллальная разработка:** Команды могут работать над ядром и адаптерами параллельно.
5. **Гибкость развёртывания:** Приложение можно развернуть как CLI, веб-сервис или desktop-приложение без изменения ядра.

## Предварительные требования

Для успешного применения паттерна необходимо владение следующими темами:
*   **Принципы SOLID:** В особенности **D** (Dependency Inversion) — зависимости должны быть направлены от внешних слоев к ядру, а не наоборот.
*   **Domain-Driven Design (DDD):** Базовое понимание сущностей (Entities), агрегатов (Aggregates), ограниченных контекстов (Bounded Context) и тактических паттернов DDD.
*   **Внедрение зависимостей (Dependency Injection):** Навык работы с DI-контейнерами или ручной сборкой зависимостей.
*   **Тестирование:** Понимание паттернов тестирования (Test Doubles: Mock, Stub, Spy, Fake) и принципов их использования.

### Связь с другими паттернами
Гексагональная архитектура является частью семейства архитектур, основанных на **принципе инверсии зависимостей**:

| Паттерн | Ключевое отличие | Уровень абстракции |
| :--- | :--- | :--- |
| **Гексагональная** | Фокус на портах и адаптерах | Интерфейсы как контракты |
| **Clean Architecture** | Чёткое разделение на слои (Use Cases, Interface Adapters, Frameworks) | Концентрические круги |
| **Onion Architecture** | Ядро окружено доменными сервисами | Концентрические слои |

Все три паттерна следуют инверсии зависимостей, но гексагональная архитектура делает акцент на **заменяемости** компонентов через стандартизированные интерфейсы.

## Базовые концепции

### Ключевые компоненты

- **Ядро (Core / Domain):**
  - Содержит чистую бизнес-логику, сущности (Entities), доменные службы и правила.
  - Это самая стабильная часть приложения, не зависящая от библиотек ввода-вывода или фреймворков.
  - Использует тактические паттерны **DDD**: агрегаты, стоимостные объекты (Value Objects), доменные события.
  - Не содержит ссылок на инфраструктурные компоненты (БД, HTTP-клиенты, очереди сообщений).

- **Порты (Ports):**
  - Это интерфейсы, определенные внутри Ядра.
  - **Входящие порты (Driving Ports):** Интерфейсы, через которые внешние системы управляют Ядром (Use Cases). Определяют, как внешний мир может вызывать бизнес-операции.
  - **Исходящие порты (Driven Ports):** Интерфейсы, через которые Ядро запрашивает данные или отправляет уведомления (Repositories, Clients). Ядро определяет, что ему нужно, но не знает, как это реализовано.
  - **Интерфейсные порты (Interface Ports):** Специализированные порты для работы с внешними системами (LDAP, Active Directory, внешние API).

- **Адаптеры (Adapters):**
  - **Входящие адаптеры (Driving Adapters):** Преобразуют внешние запросы в вызовы Ядра. Примеры: REST-контроллер, gRPC-сервер, CLI-обработчик, Kafka Consumer.
  - **Исходящие адаптеры (Driven Adapters):** Реализуют исходящие порты, инкапсулируя работу с технологией. Примеры: PostgreSQL Repository, S3 Client, SMTP-отправитель, LDAP-клиент.
  - **Инфраструктурные адаптеры:** Специализированные адаптеры для мониторинга, логирования, конфигурации и других инфраструктурных сервисов.

### Потоки данных в гексагональной архитектуре

```
Внешний мир → Входящий адаптер → Входящий порт → Ядро → Исходящий порт → Исходящий адаптер → Внешний мир
```

1. Внешний систем вызывает входящий адаптер (например, HTTP-запрос).
2. Входящий адаптер преобразует запрос и вызывает соответствующий входящий порт (Use Case).
3. Ядро выполняет бизнес-логику и может вызывать исходящие порты (например, сохранение данных).
4. Исходящие адаптеры реализуют эти порты, взаимодействуя с внешними системами.
5. Результат возвращается через обратный путь.

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
  findAll(): Promise<User[]>;
}
```

**2. Входящий порт (Use Case Interface):**
```typescript
// domain/ports/CreateUserPort.ts
export interface CreateUserPort {
  execute(name: string, email: string): Promise<void>;
}
```

**3. Ядро (Use Case):**
```typescript
// application/CreateUserUseCase.ts
import { UserRepository } from "../domain/ports/UserRepository";
import { User } from "../domain/models/User";

export class CreateUserUseCase implements CreateUserPort {
  constructor(private userRepo: UserRepository) {}

  async execute(name: string, email: string): Promise<void> {
    // Валидация бизнес-правил
    if (!email.includes('@')) {
      throw new Error('Invalid email format');
    }
    
    const user = new User(name, email);
    await this.userRepo.save(user);
  }
}
```

**4. Исходящий адаптер (PostgreSQL Implementation):**
```typescript
// infrastructure/db/PostgresUserAdapter.ts
import { UserRepository } from "../../domain/ports/UserRepository";
import { PrismaClient } from "@prisma/client";

export class PostgresUserAdapter implements UserRepository {
  constructor(private prisma: PrismaClient) {}

  async save(user: User): Promise<void> {
    await this.prisma.user.create({ data: { ...user } });
  }

  async findById(id: string): Promise<User | null> {
    const user = await this.prisma.user.findUnique({ where: { id } });
    return user ? new User(user.name, user.email) : null;
  }

  async findAll(): Promise<User[]> {
    const users = await this.prisma.user.findMany();
    return users.map(u => new User(u.name, u.email));
  }
}
```

**5. Входящий адаптер (Express Controller):**
```typescript
// presentation/http/UserController.ts
export class UserController {
  constructor(private createUserUseCase: CreateUserPort) {}

  async handle(req: Request, res: Response) {
    const { name, email } = req.body;
    await this.createUserUseCase.execute(name, email);
    res.status(201).send();
  }
}
```

### Инфраструктурные адаптеры для DevOps/SRE

#### Адаптер мониторинга (Health Checks)
```typescript
// infrastructure/monitoring/HealthCheckAdapter.ts
export interface HealthChecker {
  check(): Promise<HealthStatus>;
}

export class PostgreSQLHealthChecker implements HealthChecker {
  constructor(private prisma: PrismaClient) {}

  async check(): Promise<HealthStatus> {
    try {
      await this.prisma.$queryRaw`SELECT 1`;
      return { status: 'healthy', timestamp: new Date() };
    } catch (error) {
      return { status: 'unhealthy', error: error.message, timestamp: new Date() };
    }
  }
}
```

#### Адаптер логирования (Structured Logging)
```typescript
// infrastructure/logging/StructuredLogger.ts
export interface Logger {
  info(message: string, context?: Record<string, any>): void;
  error(message: string, error?: Error, context?: Record<string, any>): void;
}

export class JsonFileLogger implements Logger {
  constructor(private logFilePath: string) {}

  info(message: string, context?: Record<string, any>): void {
    const logEntry = {
      level: 'info',
      message,
      timestamp: new Date().toISOString(),
      ...context
    };
    fs.appendFileSync(this.logFilePath, JSON.stringify(logEntry) + '\n');
  }

  error(message: string, error?: Error, context?: Record<string, any>): void {
    const logEntry = {
      level: 'error',
      message,
      error: error?.message,
      stack: error?.stack,
      timestamp: new Date().toISOString(),
      ...context
    };
    fs.appendFileSync(this.logFilePath, JSON.stringify(logEntry) + '\n');
  }
}
```

#### Адаптер конфигурации (Environment-based Config)
```typescript
// infrastructure/config/EnvironmentConfigAdapter.ts
export interface Configuration {
  getDatabaseUrl(): string;
  getRedisUrl(): string;
  getLogLevel(): string;
}

export class EnvironmentConfiguration implements Configuration {
  getDatabaseUrl(): string {
    return process.env.DATABASE_URL || 'postgresql://localhost:5432/mydb';
  }

  getRedisUrl(): string {
    return process.env.REDIS_URL || 'redis://localhost:6379';
  }

  getLogLevel(): string {
    return process.env.LOG_LEVEL || 'info';
  }
}
```

#### Адаптер кэширования (Redis Cache)
```typescript
// infrastructure/cache/RedisCacheAdapter.ts
export interface CacheService {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlSeconds?: number): Promise<void>;
  delete(key: string): Promise<void>;
}

export class RedisCacheAdapter implements CacheService {
  constructor(private redis: Redis) {}

  async get(key: string): Promise<string | null> {
    return await this.redis.get(key);
  }

  async set(key: string, value: string, ttlSeconds?: number): Promise<void> {
    if (ttlSeconds) {
      await this.redis.setex(key, ttlSeconds, value);
    } else {
      await this.redis.set(key, value);
    }
  }

  async delete(key: string): Promise<void> {
    await this.redis.del(key);
  }
}
```

#### Адаптер очереди сообщений (RabbitMQ)
```typescript
// infrastructure/messaging/RabbitMQAdapter.ts
export interface MessageBroker {
  publish(queue: string, message: any): Promise<void>;
  consume(queue: string, handler: (message: any) => Promise<void>): Promise<void>;
}

export class RabbitMQAdapter implements MessageBroker {
  constructor(private connection: AmqpConnection) {}

  async publish(queue: string, message: any): Promise<void> {
    const channel = await this.connection.createChannel();
    await channel.assertQueue(queue, { durable: true });
    channel.sendToQueue(queue, Buffer.from(JSON.stringify(message)), {
      persistent: true
    });
    await channel.close();
  }

  async consume(queue: string, handler: (message: any) => Promise<void>): Promise<void> {
    const channel = await this.connection.createChannel();
    await channel.assertQueue(queue, { durable: true });
    await channel.consume(queue, async (msg) => {
      if (msg) {
        try {
          await handler(JSON.parse(msg.content.toString()));
          channel.ack(msg);
        } catch (error) {
          channel.nack(msg, false, true);
        }
      }
    });
  }
}
```

## Тестирование в гексагональной архитектуре

### Стратегии тестирования

Гексагональная архитектура обеспечивает естественную поддержку различных уровней тестирования благодаря четкому разделению компонентов.

#### Unit-тестирование ядра
Ядро тестируется полностью изолированно от инфраструктуры, используя Test Doubles для имитации адаптеров:

```typescript
// test/domain/CreateUserUseCase.test.ts
import { CreateUserUseCase } from '../../application/CreateUserUseCase';
import { UserRepository } from '../../domain/ports/UserRepository';

describe('CreateUserUseCase', () => {
  let useCase: CreateUserUseCase;
  let mockUserRepo: jest.Mocked<UserRepository>;

  beforeEach(() => {
    mockUserRepo = {
      save: jest.fn(),
      findById: jest.fn(),
      findAll: jest.fn(),
    };
    useCase = new CreateUserUseCase(mockUserRepo);
  });

  it('should save user with valid data', async () => {
    await useCase.execute('John', 'john@example.com');
    expect(mockUserRepo.save).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'John', email: 'john@example.com' })
    );
  });

  it('should throw error for invalid email', async () => {
    await expect(useCase.execute('John', 'invalid')).rejects.toThrow('Invalid email format');
  });
});
```

#### Интеграционное тестирование адаптеров
Адаптеры тестируются с реальными внешними системами в изолированных средах:

```typescript
// test/integration/PostgresUserAdapter.test.ts
import { PostgresUserAdapter } from '../../infrastructure/db/PostgresUserAdapter';
import { PrismaClient } from '@prisma/client';

describe('PostgresUserAdapter', () => {
  let adapter: PostgresUserAdapter;
  let prisma: PrismaClient;

  beforeAll(async () => {
    prisma = new PrismaClient();
    adapter = new PostgresUserAdapter(prisma);
  });

  afterAll(async () => {
    await prisma.$disconnect();
  });

  beforeEach(async () => {
    await prisma.user.deleteMany();
  });

  it('should save and retrieve user', async () => {
    const user = new User('Test', 'test@example.com');
    await adapter.save(user);
    const found = await adapter.findById(user.id);
    expect(found).toEqual(user);
  });
});
```

#### Архитектурные тесты (ArchUnit)
Для автоматической проверки зависимостей используются архитектурные тесты:

```java
// src/test/java/com/example/ArchitectureTest.java
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

public class ArchitectureTest {
    
    @ArchTest
    static final ArchRule domain_should_not_depend_on_infrastructure =
        noClasses()
            .that().resideInAPackage("..domain..")
            .should().dependOnClassesThat()
            .resideInAPackage("..infrastructure..");
    
    @ArchTest
    static final ArchRule ports_should_be_interfaces =
        classes()
            .that().resideInAPackage("..domain.ports..")
            .should().beInterfaces();
}
```

#### Контрактные тесты для адаптеров
Для проверки соответствия адаптеров контрактам портов:

```typescript
// test/contract/UserRepositoryContract.test.ts
export function testUserRepositoryContract(createAdapter: () => UserRepository) {
  let adapter: UserRepository;

  beforeEach(() => {
    adapter = createAdapter();
  });

  it('should implement all required methods', () => {
    expect(adapter.save).toBeDefined();
    expect(adapter.findById).toBeDefined();
    expect(adapter.findAll).toBeDefined();
  });

  it('should handle save and findById cycle', async () => {
    const user = new User('Contract Test', 'contract@test.com');
    await adapter.save(user);
    const found = await adapter.findById(user.id);
    expect(found).toBeDefined();
    expect(found!.name).toBe('Contract Test');
  });
}
```

## Поиск и устранение неисправностей

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Domain содержит ORM-аннотации** | Стремление сократить код маппинга. | Использовать отдельные модели для БД и Домена. Маппинг делать в адаптере. |
| **Циклические зависимости** | Неправильное распределение интерфейсов. | Убедиться, что интерфейсы портов определены в слое Домена или Application. |
| **Толстые контроллеры** | Логика координации осталась в адаптере. | Перенести логику в Use Case (Application layer). |
| **Сложность тестирования портов** | Порт слишком широкий (Fat Interface). | Применить Interface Segregation Principle (ISP). |
| **Слишком много адаптеров** | Чрезмерная сегментация на начальном этапе. | Начинать с минимального набора адаптеров, добавлять по мере необходимости. |
| **Производительность маппинга** | Избыточное копирование объектов. | Использовать библиотеки маппинга (MapStruct, AutoMapper) или ручной оптимизированный маппинг. |
| **Сложность отладки** | Много уровней абстракции. | Использовать structured logging на каждом уровне, трассировку запросов. |
| **Миграция базы данных** | Изменение схемы затрагивает адаптеры. | Изолировать миграции в отдельном слое, использовать паттерн Repository для доступа к БД. |

### Диагностические методы

1. **Проверка зависимостей:** Используйте инструменты анализа зависимостей (jdeps, madge, dependency-cruiser) для визуализации связей между модулями.
2. **Тестирование изоляции:** Временно замените адаптеры на in-memory реализации и проверьте, работает ли ядро.
3. **Логирование на границах:** Добавьте логирование на входе/выходе каждого порта для отслеживания потоков данных.
4. **Мониторинг производительности:** Отслеживайте время выполнения операций в адаптерах для выявления узких мест.

## Лучшие практики

### Архитектурные принципы

1.  **Маппинг всегда в адаптерах:** Ядро никогда не должно импортировать ничего из `infrastructure` или `presentation`.
2.  **DTO для каждого уровня:** Используйте Request DTO для контроллеров и Domain Entities для ядра. Это предотвращает случайное изменение API при рефакторинге логики.
3.  **Dependency Injection:** Используйте DI-контейнеры (InversifyJS, NestJS DI, Spring IoC) для автоматизации сборки гексагона.
4.  **Unit-тестирование Ядра:** Ядро должно тестироваться без запуска БД или серверов, используя простые In-memory моки портов.
5.  **Минимизация зависимостей ядра:** Ядро не должно зависеть от сторонних библиотек, если это возможно. Используйте стандартные интерфейсы языка.
6.  **Единый источник правды для моделей:** Доменные модели не должны дублироваться. Используйте единый набор моделей для ядра и адаптеров с маппингом на границе.

### DevOps и SRE практики

7.  **Health Check эндпоинты:** Каждый адаптер должен предоставлять health check для мониторинга доступности внешних систем.
8.  **Circuit Breaker паттерн:** Реализуйте circuit breaker в адаптерах для предотвращения каскадных сбоев при недоступности внешних сервисов.
9.  **Structured Logging:** Используйте структурированное логирование (JSON) для удобства парсинга и анализа.
10. **Метрики адаптеров:** Собирайте метрики времени отклика, количества ошибок и использования ресурсов для каждого адаптера.
11. **Конфигурация через окружение:** Все настройки адаптеров (URLы БД, ключи API) должны передаваться через переменные окружения.
12. **Graceful Shutdown:** Реализуйте корректное завершение работы адаптеров при остановке приложения (закрытие соединений, завершение операций).

### Безопасность

13. **Изоляция секретов:** Секреты (пароли, токены) не должны храниться в коде. Используйте vault-решения или переменные окружения.
14. **Валидация входных данных:** Все входящие данные должны валидироваться на границе адаптера перед передачей в ядро.
15. **Защита от инъекций:** Используйте параметризованные запросы для БД, экранирование вывода для HTTP.
16. **Аудит доступа:** Логируйте все попытки доступа к критическим операциям для аудита безопасности.
17. **Шифрование данных:** Шифруйте конфиденциальные данные как при хранении, так и при передаче между адаптерами.
18. **Разделение прав доступа:** Реализуйте разграничение доступа на уровне портов (разные роли могут иметь доступ к разным операциям).

### Производительность

19. **Кэширование на уровне адаптеров:** Реализуйте кэширование в адаптерах для часто запрашиваемых данных.
20. **Пул соединений:** Используйте пулы соединений для БД и внешних сервисов для переиспользования ресурсов.
21. **Асинхронные операции:** Используйте async/await или реактивные паттерны для неблокирующего ввода-вывода.
22. **Батчинг операций:** Группируйте операции для снижения накладных расходов на сетевые вызовы.

## Современные тренды (2026)

### WebAssembly (WASM) плагины
Благодаря изоляции ядра, его можно компилировать в WebAssembly и запускать на различных платформах без изменений кода. WASM обеспечивает:
- **Портативность:** Один бинарник работает на Linux, Windows, macOS и в браузере.
- **Безопасность:** Изоляция в sandbox-окружении с ограниченными правами.
- **Производительность:** Близка к нативному коду для большинства сценариев.
- **Минимальный footprint:** Бинарники размером в несколько мегабайт.

### Event-Driven архитектура
Интеграция с событийными шинами (Kafka, RabbitMQ, NATS) через адаптеры:
- **Domain Events:** Ядро генерирует события бизнес-домена.
- **Event Store:** Адаптер для сохранения событий и восстановления состояния агрегатов.
- **CQRS:** Разделение чтения и записи через разные адаптеры для оптимизации производительности.

### Архитектурные линтеры и статический анализ
Автоматизация проверки правил зависимостей становится обязательным этапом Pre-commit хуков:
- **ArchUnit (Java):** декларативные правила для проверки архитектурных ограничений.
- **dependency-cruiser (JS/TS):** визуализация и проверка графа зависимостей.
- **pylint (Python):** проверка циклических зависимостей и нарушения слоев.

### Container-First разработка
Гексагональная архитектура естественно поддерживает контейнеризацию:
- **Микроконтейнеры:** Ядро упаковывается в минимальный контейнер (distroless, alpine).
- **Sidecar адаптеры:** Инфраструктурные адаптеры (мониторинг, логирование) выносятся в отдельные контейнеры.
- **Init контейнеры:** Инициализация адаптеров (миграции БД, загрузка конфигурации) в init-контейнерах.

### GitOps для конфигурации
Управление конфигурацией адаптеров через Git:
- **Deklarativная конфигурация:** Все настройки адаптеров описываются в YAML/JSON файлах.
- **Версионирование:** История изменений конфигурации хранится в Git.
- **Автоматическое применение:** Изменения конфигурации автоматически применяются при коммите.

## Дополнительная информация

### Паттерны deployment для гексагональных приложений

1. **Monolith Deployment:** Все адаптеры и ядро в одном процессе. Простота развёртывания, но ограниченная масштабируемость.
2. **Modular Monolith:** Ядро разделено на модули, каждый со своими адаптерами. Баланс между простотой и масштабируемостью.
3. **Microservices:** Каждый доменный контекст — отдельный микросервис с набором адаптеров. Максимальная масштабируемость, но сложность управления.
4. **Hybrid:** Ядро в контейнере, адаптеры в sidecar-контейнерах или внешних сервисах.

### Инструменты для гексагональной архитектуры

| Категория | Инструменты | Назначение |
| :--- | :--- | :--- |
| **DI-контейнеры** | InversifyJS, NestJS DI, Spring IoC, Guice | Управление зависимостями |
| **Тестирование** | Jest, JUnit, PyTest, ArchUnit | Unit, интеграционные и архитектурные тесты |
| **Логирование** | Winston, Serilog, Logback | Структурированное логирование |
| **Мониторинг** | Prometheus, OpenTelemetry, Jaeger | Сбор метрик и трассировка |
| **Миграции БД** | Flyway, Liquibase, Alembic | Управление версиями схемы БД |

### См. также
*   **[Монолит и микросервисы](./monolith_vs_microservices.md)** — архитектурные подходы и выбор стратегии.
*   **[Инфраструктура как код (IaC)](./iac_overview.md)** — автоматизация развертывания адаптеров.
*   **[Событийная архитектура](../Kafka/kafka_overview.md)** — использование брокеров сообщений как адаптеров.
