// Stella Conference has no paid license: access comes from the Stella account (start it from Stella.exe).
export const GetLicense = (_props: {
  setState?: React.Dispatch<React.SetStateAction<boolean>>;
  buttonText?: string;
  buttonClassName?: string;
}) => (
  <span className="text-xs text-muted-foreground">
    Запустите из Stella: переключатель «Конференция»
  </span>
);
