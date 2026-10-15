import { useI18n } from "../lib/I18nContext";

export default function ApiNotConfigured({ configPath, onRetry }: { configPath: string; onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <div className="splash">
      <div className="apiConfigError">
        <div className="apiConfigErrorTitle">{t("api_not_configured_title", "Не настроены адреса сервера")}</div>
        <div>
          {t("api_not_configured_text", "Укажите адреса API в файле {path}, в секции [client], строкой api_base_urls = https://адрес1, https://адрес2")
            .replace("{path}", configPath)}
        </div>
        <button className="apiConfigErrorRetry" onClick={onRetry}>{t("btn_retry", "Повторить")}</button>
      </div>
    </div>
  );
}
