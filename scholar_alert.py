import os
import re
import imaplib
import smtplib
import email
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from bs4 import BeautifulSoup
from dotenv import load_dotenv

# 加载 .env 文件（本地测试用；GitHub Actions 中会从 Secrets 注入环境变量）
load_dotenv()

IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.qq.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))


def decode_mime_header(header):
    """解码邮件头，处理中文等编码"""
    if header is None:
        return ""
    parts = decode_header(header)
    decoded = []
    for content, charset in parts:
        if isinstance(content, bytes):
            try:
                decoded.append(content.decode(charset or "utf-8", errors="ignore"))
            except Exception:
                decoded.append(content.decode("utf-8", errors="ignore"))
        else:
            decoded.append(content)
    return "".join(decoded)


def fetch_scholar_emails():
    """连接 IMAP，读取来自 Google Scholar 的未读提醒邮件"""
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(SENDER_EMAIL, SENDER_PASSWORD)
    mail.select("INBOX")

    # 搜索所有未读邮件
    status, messages = mail.search(None, "UNSEEN")
    if status != "OK":
        print("搜索邮件失败")
        return []

    email_ids = messages[0].split()
    print(f"找到 {len(email_ids)} 封未读邮件")

    all_papers = []

    for eid in email_ids:
        status, msg_data = mail.fetch(eid, "(RFC822)")
        if status != "OK":
            continue

        msg = email.message_from_bytes(msg_data[0][1])
        from_addr = decode_mime_header(msg.get("From"))

        # 只处理 Google Scholar 提醒邮件
        if "scholaralerts-noreply@google.com" not in from_addr:
            continue

        subject = decode_mime_header(msg.get("Subject"))
        print(f"处理邮件: {subject}")

        html_content = None

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/html" and "attachment" not in content_disposition:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    html_content = payload.decode(charset, errors="ignore")
                    break
        else:
            if msg.get_content_type() == "text/html":
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                html_content = payload.decode(charset, errors="ignore")

        if html_content:
            papers = parse_scholar_html(html_content)
            all_papers.extend(papers)

        # 标记为已读，避免下次重复处理
        mail.store(eid, "+FLAGS", "\\Seen")

    mail.logout()
    return all_papers


def parse_scholar_html(html):
    """从 Google Scholar 提醒邮件的 HTML 中提取论文标题和链接"""
    soup = BeautifulSoup(html, "html.parser")
    papers = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)

        if not title or len(title) < 5:
            continue

        # 过滤出可能是论文的链接
        if (
            "scholar.google.com" in href
            or "doi.org" in href
            or "pubmed" in href
            or "nature.com" in href
            or "science.org" in href
        ):
            if title in seen:
                continue
            seen.add(title)
            papers.append({"title": title, "url": href})

    return papers


def build_email_html(papers):
    """把论文列表整理成 HTML 邮件正文"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    html = f"<h2>Google Scholar 每日更新 - {date_str}</h2>"

    if not papers:
        html += "<p>今日没有新的文献更新。</p>"
        return html

    html += "<ul>"
    for p in papers:
        html += f'<li><a href="{p["url"]}">{p["title"]}</a></li>'
    html += "</ul>"

    return html


def send_email(subject, html_body, to_email):
    """通过 SMTP 发送 HTML 邮件"""
    msg = MIMEMultipart("alternative")
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())

    print("邮件发送成功")


if __name__ == "__main__":
    papers = fetch_scholar_emails()
    html = build_email_html(papers)
    send_email("Google Scholar 每日更新", html, RECIPIENT_EMAIL)