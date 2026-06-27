-- smbc_website：網站專用獨立資料庫（與教會管理系統 smbc_db 完全分離）
-- 自給自足：自帶登入用 user 表 + 活動發布 event 表。
-- 慣例比照站內既有風格：單數表名、utf8mb4_general_ci、updatetime ON UPDATE。

-- 後台登入帳號（pwd 存 Werkzeug generate_password_hash 的 scrypt 雜湊）
CREATE TABLE IF NOT EXISTS `user` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `account` varchar(50) NOT NULL,
  `pwd` varchar(255) NOT NULL,
  `updatetime` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `account` (`account`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 活動發布（公開頁 /events?id=xxx）
CREATE TABLE IF NOT EXISTS `event` (
  `id` varchar(16) NOT NULL,                             -- 隨機 base62 短碼(非自增,用於 /events/<id>)
  `title` varchar(255) NOT NULL,
  `content` longtext DEFAULT NULL,                       -- WYSIWYG 內文（已清洗的 HTML）
  `image_path` varchar(255) DEFAULT NULL,                -- 上傳圖片相對路徑
  `published` tinyint(1) NOT NULL DEFAULT 1,             -- 1=已發布 0=草稿
  `author_id` int(11) DEFAULT NULL,                      -- 發布者，接 user.id
  `createtime` datetime NOT NULL DEFAULT current_timestamp(),
  `updatetime` datetime NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `author_id` (`author_id`),
  CONSTRAINT `event_ibfk_1` FOREIGN KEY (`author_id`) REFERENCES `user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
