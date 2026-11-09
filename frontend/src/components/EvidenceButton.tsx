// Доказательство цены: снимок страницы, адрес, время записи и проверка, что файл не изменён (хеш в журнале).
import { useState } from "react";
import { Alert, Button, Descriptions, Image, Modal, Spin, Typography } from "antd";
import { SafetyCertificateOutlined } from "@ant-design/icons";
import dayjs from "dayjs";

import { api, type EvidenceCheck, type Quote } from "../api";

export default function EvidenceButton({ quote }: { quote: Quote }) {
  const [open, setOpen] = useState(false);
  const [check, setCheck] = useState<EvidenceCheck | null>(null);
  const sha = quote.screenshot_sha256 ?? quote.html_sha256 ?? quote.source_sha256;
  if (!sha) return null;

  const show = () => {
    setOpen(true);
    setCheck(null);
    api<EvidenceCheck>(`/evidence/${sha}/verify`).then(setCheck);
  };

  return (
    <>
      <Button size="small" icon={<SafetyCertificateOutlined />} onClick={show}>
        Доказательство
      </Button>
      <Modal
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        width={1000}
        title={`${quote.source_name}${quote.region ? ` (${quote.region})` : ""}: ${Number(quote.unit_price).toLocaleString("ru-RU")} ₽`}
      >
        {check === null ? (
          <Spin />
        ) : (
          <Alert
            style={{ marginBottom: 12 }}
            type={check.ok ? "success" : "error"}
            showIcon
            message={check.ok ? "Файл не изменён: хеш совпадает и записан в журнале" : check.reason}
          />
        )}
        <Descriptions size="small" column={1} bordered style={{ marginBottom: 12 }}>
          <Descriptions.Item label="Страница">
            {quote.url && (
              <a href={quote.url} target="_blank" rel="noreferrer noopener">
                {quote.url}
              </a>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Товар на странице">{quote.offer_name}</Descriptions.Item>
          <Descriptions.Item label="Цена записана">{dayjs(quote.captured_at).format("DD.MM.YYYY HH:mm")}</Descriptions.Item>
          <Descriptions.Item label="Цена взята из">
            {quote.channel === "site"
              ? `разметки страницы (${quote.extracted_by}), кодом — не моделью`
              : `${quote.extracted_by === "excel" ? "Excel-вложения" : "текста письма"}: модель нашла строку, код сверил число с письмом`}
          </Descriptions.Item>
          {quote.source_sha256 && (
            <Descriptions.Item label="SHA-256 письма">
              <Typography.Text code copyable>
                {quote.source_sha256}
              </Typography.Text>{" "}
              <a href={`/api/evidence/${quote.source_sha256}/file`} target="_blank" rel="noreferrer">
                открыть исходное письмо
              </a>
            </Descriptions.Item>
          )}
          {quote.channel === "site" && (<><Descriptions.Item label="SHA-256 снимка">
            <Typography.Text code copyable>
              {quote.screenshot_sha256 ?? "—"}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="SHA-256 HTML">
            <Typography.Text code copyable>
              {quote.html_sha256 ?? "—"}
            </Typography.Text>{" "}
            {quote.html_sha256 && (
              <a href={`/api/evidence/${quote.html_sha256}/file`} target="_blank" rel="noreferrer">
                открыть исходный HTML
              </a>
            )}
          </Descriptions.Item></>)}
        </Descriptions>
        {quote.screenshot_sha256 && (
          <div style={{ maxHeight: 520, overflow: "auto", border: "1px solid var(--c-border)", borderRadius: 8 }}>
            <Image src={`/api/evidence/${quote.screenshot_sha256}/file`} alt="Снимок страницы" preview={false} />
          </div>
        )}
      </Modal>
    </>
  );
}
