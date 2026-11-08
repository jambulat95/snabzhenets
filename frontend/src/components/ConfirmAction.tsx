// Кнопка необратимого или юридически значимого действия с окном подтверждения (раздел 4.8).
// Заголовок — что произойдёт; тело — сумма, контрагент, последствия; кнопка — глагол действия. Без «Вы уверены?».
import { useState, type ReactNode } from "react";
import { Button, Modal, type ButtonProps } from "antd";

export default function ConfirmAction({
  title,
  children,
  okText,
  danger,
  onConfirm,
  button,
  buttonText,
}: {
  /** Что произойдёт: «Подписать счёт № 12 и отправить покупателю». */
  title: ReactNode;
  /** Сумма, контрагент, последствия. */
  children?: ReactNode;
  /** Глагол действия на кнопке подтверждения. */
  okText: string;
  danger?: boolean;
  onConfirm: () => Promise<unknown> | unknown;
  button?: ButtonProps;
  buttonText: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <Button danger={danger} {...button} onClick={() => setOpen(true)}>
        {buttonText}
      </Button>
      <Modal
        open={open}
        title={title}
        okText={okText}
        cancelText="Отмена"
        okButtonProps={{ danger, loading: busy }}
        onCancel={() => setOpen(false)}
        onOk={async () => {
          setBusy(true);
          try {
            await onConfirm();
            setOpen(false);
          } finally {
            setBusy(false);
          }
        }}
        destroyOnHidden
      >
        {children}
      </Modal>
    </>
  );
}
