/**
 * 补全图标 —— 使用用户提供的 SVG 图标
 * 用法: <FillMissingIcon size={16} className="..." />
 */
export const FillMissingIcon = ({ size = 16, className }) => (
  <img
    className={className}
    src="/fill-missing.svg"
    alt="补全"
    width={size}
    height={size}
    style={{ display: 'inline-block', verticalAlign: '-0.125em' }}
  />
)

