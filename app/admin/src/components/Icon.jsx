import { Icon as IconifyIcon } from '@iconify/react';

const Icon = ({ icon, size = 24, color, style, className, ...props }) => {
  return (
    <IconifyIcon
      icon={icon}
      width={size}
      height={size}
      style={{ color, display: 'inline-flex', ...style }}
      className={className}
      {...props}
    />
  );
};

export default Icon;
