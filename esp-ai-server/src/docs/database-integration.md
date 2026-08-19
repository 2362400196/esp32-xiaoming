# 数据库集成指南

## 概述

本项目设计为零数据库架构，便于未来快速集成数据库。当前使用内存存储，所有数据访问通过 Repository 接口进行抽象，未来只需实现这些接口即可切换到数据库。

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    Domain Layer (领域层)                     │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              Repository Interfaces (仓储接口)           │  │
│  │  - UserRepository (用户仓储)                          │  │
│  │  - DeviceRepository (设备仓储)                        │  │
│  │  - SessionRepository (会话仓储)                       │  │
│  │  - ToolConfigRepository (工具配置仓储)                │  │
│  │  - AuditLogRepository (审计日志仓储)                  │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                Infrastructure Layer (基础设施层)              │
│  ┌─────────────────────────────────────────────────────┐  │
│  │           Repository Implementations (仓储实现)       │  │
│  │                                                      │  │
│  │  当前：内存实现                                        │  │
│  │  └── InMemoryUserRepository                          │  │
│  │  └── InMemoryDeviceRepository                       │  │
│  │  └── InMemorySessionRepository                      │  │
│  │                                                      │  │
│  │  未来：数据库实现 (示例)                               │  │
│  │  └── SQLAlchemyUserRepository                        │  │
│  │  └── SQLAlchemyDeviceRepository                      │  │
│  │  └── PostgreSQLUserRepository (生产环境推荐)          │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 快速集成数据库

### 步骤 1: 安装数据库依赖

```bash
# PostgreSQL (推荐生产环境)
uv add asyncpg sqlalchemy

# MySQL
uv add aiomysql sqlalchemy

# SQLite (轻量级)
uv add aiosqlite sqlalchemy
```

### 步骤 2: 创建数据库实现

创建 `src/infrastructure/repositories_db.py`:

```python
"""
数据库仓储实现示例 - PostgreSQL
"""
from typing import Dict, List, Optional, Any
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, String, Boolean, Float, JSON, Integer

from src.domain.repositories import (
    UserRepository,
    DeviceRepository,
    SessionRepository,
)

Base = declarative_base()


class DBUser(Base):
    __tablename__ = "users"

    user_id = Column(String(64), primary_key=True)
    api_key = Column(String(128), unique=True, nullable=False)
    name = Column(String(128))
    email = Column(String(256))
    config = Column(JSON)
    created_at = Column(Float)
    updated_at = Column(Float)


class DBDevice(Base):
    __tablename__ = "devices"

    device_id = Column(String(64), primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    key = Column(String(128), unique=True, nullable=False)
    name = Column(String(128))
    mac_address = Column(String(32))
    asr_provider = Column(String(32))
    llm_type = Column(String(32))
    tts_type = Column(String(32))
    asr_config = Column(JSON)
    tts_config = Column(JSON)
    llm_config = Column(JSON)
    mcp_servers = Column(JSON)
    is_online = Column(Boolean, default=False)
    last_seen = Column(Float)
    created_at = Column(Float)
    updated_at = Column(Float)


class PostgreSQLUserRepository(UserRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        result = await self._session.execute(
            select(DBUser).where(DBUser.user_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        return self._to_dict(db_user) if db_user else None

    async def get_by_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        result = await self._session.execute(
            select(DBUser).where(DBUser.api_key == api_key)
        )
        db_user = result.scalar_one_or_none()
        return self._to_dict(db_user) if db_user else None

    async def create(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        db_user = DBUser(**user_data)
        self._session.add(db_user)
        await self._session.commit()
        return self._to_dict(db_user)

    async def update(self, user_id: str, user_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        result = await self._session.execute(
            select(DBUser).where(DBUser.user_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        if db_user:
            for key, value in user_data.items():
                setattr(db_user, key, value)
            await self._session.commit()
            return self._to_dict(db_user)
        return None

    async def delete(self, user_id: str) -> bool:
        result = await self._session.execute(
            select(DBUser).where(DBUser.user_id == user_id)
        )
        db_user = result.scalar_one_or_none()
        if db_user:
            await self._session.delete(db_user)
            await self._session.commit()
            return True
        return False

    async def list_all(self) -> List[Dict[str, Any]]:
        result = await self._session.execute(select(DBUser))
        return [self._to_dict(u) for u in result.scalars()]

    async def exists(self, user_id: str) -> bool:
        result = await self._session.execute(
            select(DBUser).where(DBUser.user_id == user_id)
        )
        return result.scalar_one_or_none() is not None

    def _to_dict(self, db_user: DBUser) -> Dict[str, Any]:
        return {
            "user_id": db_user.user_id,
            "api_key": db_user.api_key,
            "name": db_user.name,
            "email": db_user.email,
            "config": db_user.config,
        }


# 类似实现 DeviceRepository, SessionRepository 等...
```

### 步骤 3: 修改工厂函数

编辑 `src/infrastructure/repositories.py`:

```python
# 选择存储方式 (可通过环境变量控制)
import os

USE_DATABASE = os.getenv("USE_DATABASE", "false").lower() == "true"


def create_user_repository() -> UserRepository:
    if USE_DATABASE:
        # 数据库实现
        from src.infrastructure.repositories_db import PostgreSQLUserRepository
        # 需要配置数据库连接...
        return PostgreSQLUserRepository(session)
    else:
        # 内存实现
        return InMemoryUserRepository()
```

### 步骤 4: 添加数据库迁移

```bash
# 使用 Alembic 进行数据库迁移
uv add alembic
alembic init alembic
```

## 数据库表设计

### users 表

```sql
CREATE TABLE users (
    user_id VARCHAR(64) PRIMARY KEY,
    api_key VARCHAR(128) UNIQUE NOT NULL,
    name VARCHAR(128),
    email VARCHAR(256),
    config JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_api_key ON users(api_key);
```

### devices 表

```sql
CREATE TABLE devices (
    device_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id),
    key VARCHAR(128) UNIQUE NOT NULL,
    name VARCHAR(128),
    mac_address VARCHAR(32),
    asr_provider VARCHAR(32),
    llm_type VARCHAR(32),
    tts_type VARCHAR(32),
    asr_config JSONB,
    tts_config JSONB,
    llm_config JSONB,
    mcp_servers JSONB,
    is_online BOOLEAN DEFAULT FALSE,
    last_seen TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_devices_user_id ON devices(user_id);
CREATE INDEX idx_devices_key ON devices(key);
CREATE INDEX idx_devices_mac ON devices(mac_address);
```

### sessions 表

```sql
CREATE TABLE sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL REFERENCES devices(device_id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB
);

CREATE INDEX idx_sessions_device_id ON sessions(device_id);
```

### messages 表

```sql
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL REFERENCES sessions(session_id),
    role VARCHAR(32) NOT NULL,
    content TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_session_id ON messages(session_id);
CREATE INDEX idx_messages_created_at ON messages(created_at);
```

### audit_logs 表

```sql
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(64),
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64),
    resource_id VARCHAR(64),
    details JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);
```

## 推荐技术栈

### 开发环境
- **SQLite** - 轻量、无需安装、适合开发测试

### 生产环境
- **PostgreSQL** - 功能强大、稳定性高、异步支持好
- **MySQL** - 广泛使用、生态成熟

### ORM 选择
- **SQLAlchemy 2.0** - 异步支持好、类型安全
- **Tortoise ORM** - 专为 asyncio 设计、轻量

## 注意事项

1. **渐进式迁移** - 可以先迁移一个 Repository，其他继续使用内存实现
2. **索引优化** - 根据查询模式添加合适的索引
3. **连接池** - 生产环境务必使用连接池
4. **事务管理** - 确保数据一致性
5. **备份策略** - 定期备份数据库
