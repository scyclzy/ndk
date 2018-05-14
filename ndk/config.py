major = 17
hotfix = 1
hotfix_str = chr(ord('a') + hotfix) if hotfix else ''
beta = 0
beta_str = '-beta{}'.format(beta) if beta > 0 else ''
canary = True
canary_str = '-canary' if canary else ''
release = 'r{}{}{}{}'.format(major, hotfix_str, beta_str, canary_str)
if __name__ == '__main__':
    print release
